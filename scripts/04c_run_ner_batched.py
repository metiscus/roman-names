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

# Load environment variables from .env
load_dotenv()

# Define the Structured Output Schema for Batching
class Person(BaseModel):
    praenomen: Optional[str] = Field(None)
    nomen: Optional[str] = Field(None)
    cognomen: Optional[str] = Field(None)
    gender: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    raw_name: str
    fragmentary: bool = Field(False)

class InscriptionResult(BaseModel):
    id: str
    persons: List[Person]

class BatchNEROutput(BaseModel):
    results: List[InscriptionResult]

DAMAGE_THRESHOLD = 0.30

def damage_ratio(text):
    stripped = re.sub(r'\[[^\]]*\]', '', text)
    return (len(text) - len(stripped)) / len(text) if text else 0

def run_ner_eval_batched(province):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found.")
        return

    client = genai.Client(api_key=api_key)
    system_prompt = get_system_prompt(province)

    safe_name = province.lower().replace(' ', '_')
    eval_path = f'data/eval/{safe_name}_eval.jsonl'
    results_path = f'data/eval/{safe_name}_ner_results_batched.json'

    if not os.path.exists(eval_path):
        print(f"Error: Eval set {eval_path} not found.")
        return

    all_records = []
    with open(eval_path, 'r', encoding='utf-8') as f:
        for line in f:
            all_records.append(json.loads(line))
    
    # Pre-filter
    all_records = [r for r in all_records if damage_ratio(r['text']) <= DAMAGE_THRESHOLD]
    print(f"Starting batched evaluation run for {len(all_records)} records in '{province}'...")

    batch_size = 10
    final_results = []

    for i in tqdm(range(0, len(all_records), batch_size), desc="Processing batches"):
        batch = all_records[i:i+batch_size]
        batch_input = [{"id": r['id'], "text": r['text']} for r in batch]
        
        try:
            time.sleep(1)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
                config={
                    'system_instruction': system_prompt,
                    'response_mime_type': 'application/json',
                    'response_schema': BatchNEROutput,
                    'thinking_config': {'thinking_budget': 0},
                }
            )
            
            batch_data = response.parsed.model_dump()
            
            for pred in batch_data['results']:
                gt_record = next((r for r in batch if r['id'] == pred['id']), None)
                if gt_record:
                    final_results.append({
                        "id": pred['id'],
                        "text": gt_record['text'],
                        "ground_truth": gt_record['ground_truth_people'],
                        "prediction": pred['persons']
                    })
            
            if len(final_results) % 50 == 0:
                with open(results_path, 'w', encoding='utf-8') as f:
                    json.dump(final_results, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            print(f"\n  Error at {i}: {e}")
    
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved results to {results_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batched NER evaluation for a specific province.")
    parser.add_argument("--province", type=str, default="Africa proconsularis", help="The province name")
    args = parser.parse_args()
    
    run_ner_eval_batched(args.province)
