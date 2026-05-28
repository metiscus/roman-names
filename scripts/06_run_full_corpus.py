import os
import json
import re
import time
import argparse
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from prompt_utils import get_system_prompt
from config import EDCS_PATH, OUTPUT_DIR

load_dotenv()

DAMAGE_THRESHOLD = 0.30
BATCH_SIZE = 15            # smaller batches cut output-truncation parse errors and improve per-item rule adherence
MAX_OUTPUT_TOKENS = 65536  # explicit high cap so dense (large-roster) batches don't truncate mid-JSON

# Pricing (est) per 1M tokens
PRICING = {
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40}
}

GENDER_VALUES = {'male', 'female', 'unknown', 'homo', 'vir', 'mulier'}

# Substrings marking a transient, worth-retrying API failure.
RETRYABLE = ('429', 'quota', 'resource', 'rate', '500', '502', '503', '504',
             'unavailable', 'deadline', 'timeout', 'timed out', 'internal',
             'connection', 'reset', 'temporarily', 'overloaded')


def _is_retryable(err_str):
    s = (err_str or '').lower()
    return any(m in s for m in RETRYABLE)


def _err_label(err_str):
    """Coarse category for the end-of-run error breakdown."""
    s = (err_str or '').lower()
    if 'parse_error' in s:
        return 'parse_error (truncated/invalid JSON)'
    if '429' in s or 'quota' in s or 'rate' in s:
        return 'rate_limit (429)'
    if any(m in s for m in ('500', '502', '503', '504', 'unavailable', 'internal', 'overloaded')):
        return 'server_5xx'
    if any(m in s for m in ('timeout', 'timed out', 'deadline', 'connection', 'reset')):
        return 'network/timeout'
    return 'other'

class Person(BaseModel):
    praenomen: Optional[str] = Field(None)
    nomen: Optional[str] = Field(None)
    cognomen: Optional[str] = Field(None)
    gender: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    raw_name: str
    fragmentary: bool = Field(False)

    def model_post_init(self, __context):
        for field in ('praenomen', 'nomen', 'cognomen', 'status', 'gender'):
            val = getattr(self, field)
            if isinstance(val, str) and val.strip().lower() == 'null':
                object.__setattr__(self, field, None)
        for field in ('praenomen', 'nomen', 'cognomen'):
            val = getattr(self, field)
            if val and val.lower().strip() in GENDER_VALUES:
                object.__setattr__(self, field, None)

class InscriptionResult(BaseModel):
    id: str
    persons: List[Person]

class BatchNEROutput(BaseModel):
    results: List[InscriptionResult]

def damage_ratio(text):
    stripped = re.sub(r'\[[^\]]*\]', '', text)
    return (len(text) - len(stripped)) / len(text) if text else 1.0

def load_records(province):
    print(f"Loading EDCS data for {province}...")
    with open(EDCS_PATH, encoding='utf-8') as f:
        data = json.load(f)

    records = []
    for r in data:
        if r.get('province') != province:
            continue
        text = str(r.get('inscription') or r.get('clean_text_interpretive_word') or '').strip()
        if not text or text == '?':
            continue
        if damage_ratio(text) > DAMAGE_THRESHOLD:
            continue
        records.append({'id': r['EDCS-ID'], 'text': text})

    print(f"Loaded {len(records)} records for {province} after damage filtering.")
    return records

def load_processed_ids(output_path):
    if not os.path.exists(output_path):
        return set()
    ids = set()
    with open(output_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                ids.add(json.loads(line)['id'])
            except Exception:
                pass
    return ids

def main():
    parser = argparse.ArgumentParser(description="Run full corpus NER for a specific province.")
    parser.add_argument("--province", type=str, default="Africa proconsularis", help="The province name")
    parser.add_argument("--stop-after", type=int, default=None, metavar="N",
                        help="Stop after processing N new records (for supervised runs). "
                             "Re-run without this flag to continue from where it stopped.")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash-lite",
                        help="Gemini model to use (default: gemini-2.5-flash-lite)")
    parser.add_argument("--workers", type=int, default=10,
                        help="Concurrent API workers (default: 10; Flash-Lite supports up to ~50)")
    args = parser.parse_args()

    province = args.province
    stop_after = args.stop_after
    model = args.model
    workers = args.workers
    safe_name = re.sub(r'[()]', '', province).lower().replace(' ', '_')
    output_path = OUTPUT_DIR / f'{safe_name}_ner_full.jsonl'

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found.")
        return

    client = genai.Client(api_key=api_key)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_records = load_records(province)
    processed_ids = load_processed_ids(output_path)

    remaining = [r for r in all_records if r['id'] not in processed_ids]
    print(f"Already processed: {len(processed_ids)} | Remaining: {len(remaining)}")

    if stop_after:
        remaining = remaining[:stop_after]
        print(f"--stop-after {stop_after}: will process at most {len(remaining)} records this run.")

    if not remaining:
        print("All records already processed.")
        return

    system_prompt = get_system_prompt(province)
    batches = [remaining[i:i + BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]
    print(f"Workers: {workers} | Batches: {len(batches)} | Model: {model}")

    rates = PRICING.get(model, PRICING["gemini-2.5-flash-lite"])
    write_lock = threading.Lock()
    counters = {'new': 0, 'errors': 0, 'cost': 0.0}
    err_types = Counter()

    def process_batch(batch):
        batch_input = [{'id': r['id'], 'text': r['text']} for r in batch]
        backoff = 5
        last_err = "max_retries"
        for attempt in range(5):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
                    config={
                        'system_instruction': system_prompt,
                        'response_mime_type': 'application/json',
                        'response_schema': BatchNEROutput,
                        'thinking_config': {'thinking_budget': 0},
                        'max_output_tokens': MAX_OUTPUT_TOKENS,
                    },
                )
                usage = response.usage_metadata
                cost = (usage.prompt_token_count * rates["in"] / 1_000_000) + \
                       (usage.candidates_token_count * rates["out"] / 1_000_000)
                if response.parsed is None:
                    # Usually truncation / MAX_TOKENS — a re-roll often succeeds.
                    last_err = "parse_error"
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                return response.parsed.results, cost, None
            except Exception as e:
                last_err = str(e)
                if _is_retryable(last_err):
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                return None, 0.0, last_err  # non-retryable — give up immediately
        return None, 0.0, last_err

    with open(output_path, 'a', encoding='utf-8') as out_f:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_batch, b): b for b in batches}
            pbar = tqdm(total=len(batches), desc="Batches")
            for future in as_completed(futures):
                results, cost, error = future.result()
                with write_lock:
                    counters['cost'] += cost
                    if error:
                        counters['errors'] += 1
                        err_types[_err_label(error)] += 1
                    elif results:
                        for pred in results:
                            out_f.write(json.dumps({
                                'id': pred.id,
                                'persons': [p.model_dump() for p in pred.persons],
                            }, ensure_ascii=False) + '\n')
                            counters['new'] += 1
                        out_f.flush()
                pbar.update(1)
                pbar.set_postfix({'cost': f"${counters['cost']:.4f}", 'err': counters['errors']})
            pbar.close()

    total_now = len(load_processed_ids(output_path))
    print(f"\nThis run: {counters['new']} new records | Total: {total_now} / {len(all_records)} | "
          f"Errors: {counters['errors']} | Cost: ${counters['cost']:.4f}")
    if err_types:
        print(f"Error breakdown (each failed batch ~{BATCH_SIZE} records):")
        for label, count in err_types.most_common():
            print(f"  {count:5d} x {label}")
        print("  Re-run the same command to retry — resume skips already-written IDs.")
    if stop_after and counters['new'] >= stop_after:
        print(f"Stopped at requested limit. {len(all_records) - total_now} records remaining — re-run to continue.")

if __name__ == "__main__":
    main()
