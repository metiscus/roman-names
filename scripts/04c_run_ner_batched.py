import os
import json
import re
import time
from tqdm import tqdm
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Define the Structured Output Schema for Batching
class Person(BaseModel):
    praenomen: Optional[str] = Field(None, description="The first name (e.g., Marcus, Lucius)")
    nomen: Optional[str] = Field(None, description="The family/gentile name (e.g., Aurelius, Septimius)")
    cognomen: Optional[str] = Field(None, description="The third name or surname (e.g., Maximus, Severus)")
    gender: Optional[str] = Field(None, description="male | female | unknown")
    status: Optional[str] = Field(None, description="Social or professional status markers")
    raw_name: str = Field(..., description="The name as it appears in the text")

class InscriptionResult(BaseModel):
    id: str = Field(..., description="The ID of the inscription")
    persons: List[Person]

class BatchNEROutput(BaseModel):
    results: List[InscriptionResult]

DAMAGE_THRESHOLD = 0.30  # skip inscriptions where >30% of chars are in lacunae

def damage_ratio(text):
    """Fraction of characters inside editorial brackets (lacunae)."""
    stripped = re.sub(r'\[[^\]]*\]', '', text)
    damaged = len(text) - len(stripped)
    return damaged / len(text) if text else 0

def run_ner_eval_batched():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    client = genai.Client(api_key=api_key)
    
    # Load system prompt from file
    with open('scripts/prompts/ner_v1.txt', 'r', encoding='utf-8') as f:
        system_prompt = f.read()

    # Load eval set
    eval_path = 'data/eval/africa_proconsularis_eval.jsonl'
    all_records = []
    with open(eval_path, 'r', encoding='utf-8') as f:
        for line in f:
            all_records.append(json.loads(line))
    
    # Pre-filter heavily damaged inscriptions
    skipped = [r for r in all_records if damage_ratio(r['text']) > DAMAGE_THRESHOLD]
    all_records = [r for r in all_records if damage_ratio(r['text']) <= DAMAGE_THRESHOLD]
    print(f"Skipped {len(skipped)} heavily damaged records (>{int(DAMAGE_THRESHOLD*100)}% lacunae).")
    print(f"Starting batched evaluation run for {len(all_records)} records...")

    results_path = 'data/eval/ner_results_500_batched.json'
    batch_size = 10
    final_results = []

    # Process in batches
    for i in tqdm(range(0, len(all_records), batch_size), desc="Processing batches"):
        batch = all_records[i:i+batch_size]
        batch_input = [{"id": r['id'], "text": r['text']} for r in batch]
        
        try:
            # Short sleep to be safe, even on paid tier
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
            
            # Match results back to input records (to keep ground truth)
            for pred in batch_data['results']:
                gt_record = next((r for r in batch if r['id'] == pred['id']), None)
                if gt_record:
                    final_results.append({
                        "id": pred['id'],
                        "text": gt_record['text'],
                        "ground_truth": gt_record['ground_truth_people'],
                        "prediction": pred['persons']
                    })
            
            # Intermediate save
            if len(final_results) % 50 == 0:
                with open(results_path, 'w', encoding='utf-8') as f:
                    json.dump(final_results, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            print(f"\n  Error processing batch starting at {i}: {e}")
    
    # Final save
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)
    
    print(f"\nEvaluation run complete. {len(final_results)} records processed. Results saved to {results_path}")

if __name__ == "__main__":
    run_ner_eval_batched()
