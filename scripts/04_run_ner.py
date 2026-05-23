import os
import json
import time
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Define the Structured Output Schema using Pydantic
class Person(BaseModel):
    praenomen: Optional[str] = Field(None, description="The first name (e.g., Marcus, Lucius)")
    nomen: Optional[str] = Field(None, description="The family/gentile name (e.g., Aurelius, Septimius)")
    cognomen: Optional[str] = Field(None, description="The third name or surname (e.g., Maximus, Severus)")
    gender: Optional[str] = Field(None, description="male | female | unknown")
    status: Optional[str] = Field(None, description="Social or professional status markers")
    raw_name: str = Field(..., description="The name as it appears in the text")

class NEROutput(BaseModel):
    persons: List[Person]

from tqdm import tqdm

def run_ner_eval():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    client = genai.Client(api_key=api_key)
    
    # Load system prompt
    with open('scripts/prompts/ner_v1.txt', 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    
    # Load eval set
    eval_path = 'data/eval/africa_proconsularis_eval.jsonl'
    test_records = []
    with open(eval_path, 'r', encoding='utf-8') as f:
        for line in f:
            test_records.append(json.loads(line))
    
    print(f"Starting evaluation run for {len(test_records)} records...")
    
    results_path = 'data/eval/ner_results_500.json'
    eval_results = []
    
    # Loop with progress bar
    for record in tqdm(test_records, desc="Processing inscriptions"):
        try:
            # Add sleep for free tier rate limiting (15 RPM limit approx)
            time.sleep(4) # 4 seconds = 15 requests per minute
            
            # Use Gemini with Structured Output
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Text to process: {record['text']}",
                config={
                    'system_instruction': system_prompt,
                    'response_mime_type': 'application/json',
                    'response_schema': NEROutput,
                }
            )
            
            ner_data = response.parsed.model_dump()
            
            eval_results.append({
                "id": record['id'],
                "text": record['text'],
                "ground_truth": record['ground_truth_people'],
                "prediction": ner_data['persons']
            })
            
            # Periodically save progress
            if len(eval_results) % 10 == 0:
                with open(results_path, 'w', encoding='utf-8') as f:
                    json.dump(eval_results, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            print(f"\n  Error processing {record['id']}: {e}")
            # Optional: handle specific quota errors by sleeping longer
            if "429" in str(e):
                print("  Quota exceeded. Sleeping for 60 seconds...")
                time.sleep(60)
    
    # Final save
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(eval_results, f, indent=2, ensure_ascii=False)
    
    print(f"\nEvaluation run complete. Results saved to {results_path}")

if __name__ == "__main__":
    run_ner_eval()
