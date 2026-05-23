import os
import json
import re
import time
from tqdm import tqdm
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

PROVINCE = 'Africa proconsularis'
DAMAGE_THRESHOLD = 0.30
BATCH_SIZE = 10
OUTPUT_PATH = 'data/output/africa_proconsularis_ner_full.jsonl'

SYSTEM_PROMPT = """You are an expert Latin epigrapher specializing in the Roman inscriptions of Africa Proconsularis.
You will be provided with a list of inscriptions, each with a unique ID.
Your task is to perform Named Entity Recognition (NER) on each inscription and extract personal names.

For each person identified:
1. Deconstruct the name into praenomen, nomen, and cognomen.
2. Identify gender ('male', 'female', or 'unknown') and social/professional status markers.
3. Handle Abbreviations: Expand standard abbreviations (e.g., 'L.' to 'Lucius', 'M.' to 'Marcus', 'f.' to 'filius').
4. Return a JSON object containing a 'results' list, where each item matches an ID to its extracted persons list."""


class Person(BaseModel):
    praenomen: Optional[str] = Field(None)
    nomen: Optional[str] = Field(None)
    cognomen: Optional[str] = Field(None)
    gender: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    raw_name: str

class InscriptionResult(BaseModel):
    id: str
    persons: List[Person]

class BatchNEROutput(BaseModel):
    results: List[InscriptionResult]


def damage_ratio(text):
    stripped = re.sub(r'\[[^\]]*\]', '', text)
    return (len(text) - len(stripped)) / len(text) if text else 1.0

def load_records():
    print("Loading EDCS data...")
    with open('data/EDCS_text_cleaned_2022-09-12.json') as f:
        data = json.load(f)

    records = []
    for r in data:
        if r.get('province') != PROVINCE:
            continue
        text = str(r.get('clean_text_interpretive_word') or r.get('inscription') or '').strip()
        if not text or text == '?':
            continue
        if damage_ratio(text) > DAMAGE_THRESHOLD:
            continue
        records.append({'id': r['EDCS-ID'], 'text': text})

    print(f"Loaded {len(records)} records after damage filtering.")
    return records

def load_processed_ids():
    """Return set of IDs already saved to the output file."""
    if not os.path.exists(OUTPUT_PATH):
        return set()
    ids = set()
    with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                ids.add(json.loads(line)['id'])
            except Exception:
                pass
    return ids

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found.")
        return

    client = genai.Client(api_key=api_key)
    os.makedirs('data/output', exist_ok=True)

    all_records = load_records()
    processed_ids = load_processed_ids()

    remaining = [r for r in all_records if r['id'] not in processed_ids]
    print(f"Already processed: {len(processed_ids)} | Remaining: {len(remaining)}")

    if not remaining:
        print("All records already processed.")
        return

    errors = 0
    with open(OUTPUT_PATH, 'a', encoding='utf-8') as out_f:
        for i in tqdm(range(0, len(remaining), BATCH_SIZE), desc="Processing"):
            batch = remaining[i:i + BATCH_SIZE]
            batch_input = [{'id': r['id'], 'text': r['text']} for r in batch]

            try:
                time.sleep(1)
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
                    config={
                        'system_instruction': SYSTEM_PROMPT,
                        'response_mime_type': 'application/json',
                        'response_schema': BatchNEROutput,
                        'thinking_config': {'thinking_budget': 0},
                    },
                )
                batch_data = response.parsed.model_dump()

                for pred in batch_data['results']:
                    out_f.write(json.dumps({
                        'id': pred['id'],
                        'persons': pred['persons'],
                    }, ensure_ascii=False) + '\n')
                out_f.flush()

            except Exception as e:
                errors += 1
                print(f"\n  Error on batch {i}: {e}")
                if '429' in str(e) or 'quota' in str(e).lower():
                    print("  Quota hit — stopping. Re-run the script to resume.")
                    break
                if 'billing' in str(e).lower() or 'spend' in str(e).lower():
                    print("  Spend cap reached — stopping. Re-run the script to resume.")
                    break

    processed_now = len(load_processed_ids())
    print(f"\nDone. Total records in output: {processed_now} / {len(all_records)} | Errors: {errors}")
    if processed_now < len(all_records):
        print("Run this script again to resume from where it stopped.")

if __name__ == "__main__":
    main()
