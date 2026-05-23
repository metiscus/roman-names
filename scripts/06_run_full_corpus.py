import os
import json
import re
import time
import argparse
from tqdm import tqdm
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import sys

# Ensure scripts can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from prompt_utils import get_system_prompt

load_dotenv()

DAMAGE_THRESHOLD = 0.30
BATCH_SIZE = 10

GENDER_VALUES = {'male', 'female', 'unknown', 'homo', 'vir', 'mulier'}

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
    with open('data/EDCS_text_cleaned_2022-09-12.json') as f:
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
    args = parser.parse_args()

    province = args.province
    safe_name = province.lower().replace(' ', '_')
    output_path = f'data/output/{safe_name}_ner_full.jsonl'

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found.")
        return

    client = genai.Client(api_key=api_key)
    os.makedirs('data/output', exist_ok=True)

    all_records = load_records(province)
    processed_ids = load_processed_ids(output_path)

    remaining = [r for r in all_records if r['id'] not in processed_ids]
    print(f"Already processed: {len(processed_ids)} | Remaining: {len(remaining)}")

    if not remaining:
        print("All records already processed.")
        return

    system_prompt = get_system_prompt(province)

    errors = 0
    with open(output_path, 'a', encoding='utf-8') as out_f:
        for i in tqdm(range(0, len(remaining), BATCH_SIZE), desc="Processing"):
            batch = remaining[i:i + BATCH_SIZE]
            batch_input = [{'id': r['id'], 'text': r['text']} for r in batch]

            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
                    config={
                        'system_instruction': system_prompt,
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
                    print("  Quota hit — stopping.")
                    break

    processed_now = len(load_processed_ids(output_path))
    print(f"\nDone. Total records in output: {processed_now} / {len(all_records)} | Errors: {errors}")

if __name__ == "__main__":
    main()
