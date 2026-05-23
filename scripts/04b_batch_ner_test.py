import os
import json
import time
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

def run_ner_batch_test():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    client = genai.Client(api_key=api_key)
    
    # Updated system instruction for batching
    system_prompt = """You are an expert Latin epigrapher. You will be provided with a list of inscriptions, each with a unique ID. 
Your task is to perform Named Entity Recognition (NER) on each inscription and extract personal names.

For each person identified:
- Deconstruct the name into praenomen, nomen, and cognomen.
- Identify gender and social/professional status markers.
- Expand standard abbreviations (e.g., 'L.' to 'Lucius').

Return a JSON object containing a 'results' list, where each item matches an ID to its extracted persons."""

    # Load first 10 records (the same ones we did before)
    dev_path = 'data/eval/africa_proconsularis_dev.jsonl'
    test_records = []
    with open(dev_path, 'r', encoding='utf-8') as f:
        for _ in range(10):
            line = f.readline()
            if not line: break
            test_records.append(json.loads(line))
    
    # Prepare batch input
    batch_input = []
    for r in test_records:
        batch_input.append({"id": r['id'], "text": r['text']})
    
    print(f"Starting batch test run for {len(test_records)} records...")
    
    try:
        # Use Gemini with Structured Output for the batch
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
            config={
                'system_instruction': system_prompt,
                'response_mime_type': 'application/json',
                'response_schema': BatchNEROutput,
            }
        )
        
        batch_data = response.parsed.model_dump()
        
        # Merge with ground truth for comparison
        combined_results = []
        for pred in batch_data['results']:
            # Find matching GT
            gt = next((r for r in test_records if r['id'] == pred['id']), None)
            combined_results.append({
                "id": pred['id'],
                "text": gt['text'] if gt else "N/A",
                "ground_truth": gt['ground_truth_people'] if gt else "N/A",
                "prediction": pred['persons']
            })
            
        # Save results
        output_path = 'temp/ner_batch_test_results.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(combined_results, f, indent=2, ensure_ascii=False)
        
        print(f"\nBatch test run complete. Results saved to {output_path}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_ner_batch_test()
