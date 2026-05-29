"""
Translate inscription text using Gemini 2.5 Flash-Lite.

Reads per-province enrichment JSON files, finds records with `text_edition`
but no `translation` yet, calls the API in concurrent batches, and writes
results back incrementally.

When `text_edition` is absent, falls back to `raw_text` from the province
GeoJSON (epigraphic notation with parenthesised expansions).

Usage:
    python scripts/11_translate_inscriptions.py --province britannia
    python scripts/11_translate_inscriptions.py --province all --stop-after 500
    python scripts/11_translate_inscriptions.py --province africa_proconsularis --dry-run
    python scripts/11_translate_inscriptions.py --province all --force  # re-translate existing
"""
import argparse
import json
import os
import sys
import time
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PROVINCE_SLUGS as PROVINCES

load_dotenv()

DEFAULT_MODEL = 'gemini-2.5-flash-lite'
MIN_EDITION_LENGTH = 20
MIN_RAW_LENGTH = 15
BATCH_SIZE = 10
CHECKPOINT_EVERY = 50
MAX_OUTPUT_TOKENS = 65536

BATCH_PROMPT = """You are an expert in classical Latin epigraphy. I will give you a JSON array of Roman inscription texts as printed in scholarly editions (square brackets enclose restorations or missing characters; [---] marks illegible lacunae).

For each inscription provide:
1. An English translation (readable, not overly literal; preserve proper names).
2. A single sentence describing what this inscription records (type of monument, dedicant, recipient, approximate date if inferable).

Respond with a JSON array in the same order as the input. Each element must have exactly three keys: "id" (the EDCS-ID from the input), "translation", and "summary".

Inscriptions:
{items_json}"""


# ── Pydantic schema for structured output ─────────────────────────────────────

class TranslationResult(BaseModel):
    id: str
    translation: str
    summary: str

class BatchTranslationOutput(BaseModel):
    results: list[TranslationResult]


# ── Pricing & retry helpers ───────────────────────────────────────────────────

PRICING = {
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
}

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


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_enrichment(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def save_enrichment(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )


def load_raw_text_lookup(province: str) -> dict[str, str]:
    """Build edcs_id → raw_text from the province GeoJSON."""
    path = Path(f'webapp/data/inscriptions_{province}.geojson')
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return {
        f['properties']['edcs_id']: f['properties'].get('raw_text', '')
        for f in data.get('features', [])
        if f['properties'].get('raw_text')
    }


def find_candidates(enrichment: dict, raw_lookup: dict, force: bool,
                    include_raw: bool = False) -> list[tuple[str, str]]:
    """Return (edcs_id, text) pairs that need translation.

    Prefers text_edition; falls back to raw_text for records without one.
    When include_raw is True, also picks up records from the GeoJSON that
    have no enrichment entry at all (non-LIRE inscriptions).
    """
    out = []
    for edcs_id, rec in enrichment.items():
        if not force and rec.get('translation'):
            continue
        edition = rec.get('text_edition', '')
        if edition and len(edition) >= MIN_EDITION_LENGTH:
            out.append((edcs_id, edition))
        elif len(edition) < MIN_EDITION_LENGTH and edcs_id in raw_lookup:
            raw = raw_lookup[edcs_id]
            if len(raw) >= MIN_RAW_LENGTH:
                out.append((edcs_id, raw))
        elif edition and len(edition) >= MIN_RAW_LENGTH:
            out.append((edcs_id, edition))

    if include_raw:
        for edcs_id, raw in raw_lookup.items():
            if edcs_id in enrichment:
                continue
            if len(raw) >= MIN_RAW_LENGTH:
                # Create stub enrichment entry so translation can be stored
                enrichment[edcs_id] = {}
                out.append((edcs_id, raw))

    return out


# ── API call ──────────────────────────────────────────────────────────────────

def translate_batch(client, model: str, batch: list[tuple[str, str]]):
    """Translate a batch via the API.

    Returns (results: list[TranslationResult] | None, cost: float, error: str | None).
    """
    items = [{'id': edcs_id, 'text': text} for edcs_id, text in batch]
    prompt = BATCH_PROMPT.format(items_json=json.dumps(items, ensure_ascii=False))

    rates = PRICING.get(model, PRICING["gemini-2.5-flash-lite"])
    backoff = 5
    last_err = "max_retries"

    for _attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': BatchTranslationOutput,
                    'thinking_config': {'thinking_budget': 0},
                    'max_output_tokens': MAX_OUTPUT_TOKENS,
                },
            )
            usage = resp.usage_metadata
            cost = (usage.prompt_token_count * rates["in"] / 1_000_000) + \
                   (usage.candidates_token_count * rates["out"] / 1_000_000)

            if resp.parsed is None:
                last_err = "parse_error"
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            return resp.parsed.results, cost, None

        except Exception as e:
            last_err = str(e)
            if _is_retryable(last_err):
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            return None, 0.0, last_err

    return None, 0.0, last_err


# ── Province processing ───────────────────────────────────────────────────────

def process_province(province: str, client, model: str, workers: int,
                     batch_size: int, stop_after: int, force: bool,
                     dry_run: bool, include_raw: bool = False) -> tuple[int, int, float, Counter]:
    """Returns (translated, errors, cost, err_types)."""
    path = Path(f'webapp/data/enrichment_{province}.json')
    enrichment = load_enrichment(path)
    err_types: Counter = Counter()

    if not enrichment:
        print(f"  [{province}] No enrichment file found — skipping.")
        return 0, 0, 0.0, err_types

    raw_lookup = load_raw_text_lookup(province)
    candidates = find_candidates(enrichment, raw_lookup, force, include_raw)
    already_done = sum(1 for r in enrichment.values() if r.get('translation'))

    print(f"\n[{province}]")
    print(f"  {len(enrichment):,} enrichment records | {already_done:,} already translated | {len(candidates):,} to translate")

    if not candidates:
        return 0, 0, 0.0, err_types

    if stop_after:
        candidates = candidates[:stop_after]
        print(f"  --stop-after {stop_after}: will translate at most {len(candidates)} records this run.")

    if dry_run:
        n_batches = (len(candidates) + batch_size - 1) // batch_size
        print(f"  DRY RUN — would translate {len(candidates)} records in {n_batches} batches of {batch_size}")
        return 0, 0, 0.0, err_types

    batches = [candidates[i:i + batch_size] for i in range(0, len(candidates), batch_size)]
    print(f"  Workers: {workers} | Batches: {len(batches)} | Model: {model}")

    translated = 0
    errors = 0
    total_cost = 0.0
    checkpoint_counter = 0
    write_lock = threading.Lock()

    def _submit(batch):
        return translate_batch(client, model, batch)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_submit, b): b for b in batches}
        pbar = tqdm(total=len(batches), desc=f"  {province}", unit="batch")

        for future in as_completed(futures):
            batch = futures[future]
            results, cost, error = future.result()

            with write_lock:
                total_cost += cost
                if error:
                    errors += len(batch)
                    err_types[_err_label(error)] += 1
                elif results:
                    by_id = {r.id: r for r in results}
                    for edcs_id, _ in batch:
                        r = by_id.get(edcs_id)
                        if r and r.translation:
                            enrichment[edcs_id]['translation'] = r.translation
                            enrichment[edcs_id]['summary'] = r.summary or ''
                            translated += 1
                            checkpoint_counter += 1
                        else:
                            errors += 1

                if checkpoint_counter >= CHECKPOINT_EVERY:
                    save_enrichment(path, enrichment)
                    checkpoint_counter = 0

            pbar.update(1)
            pbar.set_postfix({'cost': f"${total_cost:.4f}", 'ok': translated, 'err': errors})

        pbar.close()

    save_enrichment(path, enrichment)
    total_now = sum(1 for r in enrichment.values() if r.get('translation'))
    print(f"  Saved {path} — {translated} new translations | {total_now}/{len(enrichment)} total | "
          f"Errors: {errors} | Cost: ${total_cost:.4f}")

    return translated, errors, total_cost, err_types


def main():
    parser = argparse.ArgumentParser(description='Translate inscription text with Gemini')
    parser.add_argument('--province', default='all',
                        help=f'Province slug or "all". Choices: {", ".join(PROVINCES)}')
    parser.add_argument('--model', default=DEFAULT_MODEL,
                        help=f'Gemini model (default: {DEFAULT_MODEL})')
    parser.add_argument('--stop-after', type=int, default=None, metavar='N',
                        help='Stop after translating N records per province (for supervised runs). '
                             'Re-run without this flag to continue.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be translated without calling the API')
    parser.add_argument('--force', action='store_true',
                        help='Re-translate records that already have a translation')
    parser.add_argument('--include-raw', action='store_true',
                        help='Also translate non-LIRE inscriptions using EDCS raw text')
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE,
                        help=f'Inscriptions per API call (default: {BATCH_SIZE})')
    parser.add_argument('--workers', type=int, default=10,
                        help='Concurrent API workers (default: 10)')
    args = parser.parse_args()

    if not Path('webapp/data').exists():
        os.chdir(Path(__file__).parent.parent)

    if not args.dry_run:
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            print('ERROR: GEMINI_API_KEY not set in .env', file=sys.stderr)
            sys.exit(1)
        client = genai.Client(api_key=api_key)
    else:
        client = None

    provinces = PROVINCES if args.province == 'all' else [args.province]
    if args.province != 'all' and args.province not in PROVINCES:
        print(f'ERROR: unknown province "{args.province}"', file=sys.stderr)
        sys.exit(1)

    total_translated = 0
    total_errors = 0
    total_cost = 0.0
    all_err_types: Counter = Counter()

    for prov in provinces:
        t, e, c, et = process_province(
            prov, client, args.model, args.workers,
            args.batch_size, args.stop_after, args.force, args.dry_run,
            args.include_raw,
        )
        total_translated += t
        total_errors += e
        total_cost += c
        all_err_types += et

    print(f'\nDone. Translated: {total_translated} | Errors: {total_errors} | Cost: ${total_cost:.4f}')
    if all_err_types:
        print(f"Error breakdown (each failed batch ≈ {args.batch_size} records):")
        for label, count in all_err_types.most_common():
            print(f"  {count:5d} × {label}")
        print("  Re-run the same command to retry — resume skips already-translated IDs.")


if __name__ == '__main__':
    main()
