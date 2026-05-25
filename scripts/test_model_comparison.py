import os
import json
import time
import argparse
from tqdm import tqdm
from google import genai
from pydantic import BaseModel
from dotenv import load_dotenv
from prompt_utils import get_system_prompt

load_dotenv()

class Person(BaseModel):
    praenomen: str | None
    nomen: str | None
    cognomen: str | None
    gender: str | None
    status: str | None
    raw_name: str
    fragmentary: bool

class BatchResult(BaseModel):
    id: str
    persons: list[Person]

class BatchNEROutput(BaseModel):
    results: list[BatchResult]

def run_comparison(province="Numidia", sample_size=30):
    api_key = os.getenv('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)
    
    # Load Numidia records (using first 30 as sample)
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("run_full_corpus", "scripts/06_run_full_corpus.py")
    rfc = importlib.util.module_from_spec(spec)
    sys.modules["run_full_corpus"] = rfc
    spec.loader.exec_module(rfc)
    all_records = rfc.load_records(province)
    sample = all_records[:sample_size]
    
    batch_input = [{'id': r['id'], 'text': r['text']} for r in sample]
    system_prompt = get_system_prompt(province)
    
    models = [
        {"name": "gemini-2.5-flash", "label": "Flash Standard"},
        {"name": "gemini-2.5-flash-lite", "label": "Flash Lite"}
    ]
    
    comparison_results = {}

    for model_info in models:
        model_name = model_info['name']
        print(f"\nRunning {model_info['label']} ({model_name})...")
        
        start_time = time.time()
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
                config={
                    'system_instruction': system_prompt,
                    'response_mime_type': 'application/json',
                    'response_schema': BatchNEROutput,
                    'thinking_config': {'thinking_budget': 0},
                },
            )
            elapsed = time.time() - start_time
            usage = response.usage_metadata
            
            # Pricing (est)
            if "lite" in model_name:
                in_rate, out_rate = 0.10, 0.40
            else:
                in_rate, out_rate = 0.30, 2.50
                
            cost = (usage.prompt_token_count * in_rate / 1_000_000) + (usage.candidates_token_count * out_rate / 1_000_000)
            
            comparison_results[model_name] = {
                "usage": {
                    "prompt_token_count": usage.prompt_token_count,
                    "candidates_token_count": usage.candidates_token_count,
                    "total_token_count": usage.total_token_count
                },
                "cost": cost,
                "elapsed": elapsed,
                "data": response.parsed.model_dump()
            }
            
            print(f"  Tokens: In={usage.prompt_token_count}, Out={usage.candidates_token_count}")
            print(f"  Cost: ${cost:.6f}")
            print(f"  Time: {elapsed:.2f}s")
            
        except Exception as e:
            print(f"  Error with {model_name}: {e}")

    # Final summary and semantic diff
    print("\n" + "="*50)
    print("COMPARISON SUMMARY")
    print("="*50)
    
    f_results = comparison_results.get("gemini-2.5-flash", {}).get("data", {}).get("results", [])
    l_results = comparison_results.get("gemini-2.5-flash-lite", {}).get("data", {}).get("results", [])
    
    f_dict = {r['id']: r['persons'] for r in f_results}
    l_dict = {r['id']: r['persons'] for r in l_results}
    
    semantic_matches = 0
    diffs = []
    
    for rid in [r['id'] for r in sample]:
        f_pers = f_dict.get(rid, [])
        l_pers = l_dict.get(rid, [])
        
        # Normalize for comparison: sort by raw_name
        f_pers_norm = sorted(f_pers, key=lambda x: x['raw_name'])
        l_pers_norm = sorted(l_pers, key=lambda x: x['raw_name'])
        
        if json.dumps(f_pers_norm, sort_keys=True) == json.dumps(l_pers_norm, sort_keys=True):
            semantic_matches += 1
        else:
            diffs.append((rid, f_pers_norm, l_pers_norm))
            
    print(f"Semantic Matches: {semantic_matches}/{sample_size} ({semantic_matches/sample_size:.1%})")
    
    if diffs:
        print("\nTOP 3 DIFFERENCES:")
        for rid, fp, lp in diffs[:3]:
            print(f"\nID: {rid}")
            print(f"  FLASH: {json.dumps(fp, ensure_ascii=False)}")
            print(f"  LITE:  {json.dumps(lp, ensure_ascii=False)}")
    
    f_cost = comparison_results.get("gemini-2.5-flash", {}).get("cost", 0)
    l_cost = comparison_results.get("gemini-2.5-flash-lite", {}).get("cost", 0)
    
    print(f"\nFlash Cost:     ${f_cost:.6f}")
    print(f"Flash-Lite Cost: ${l_cost:.6f}")
    print(f"Savings:        {(1 - l_cost/f_cost):.1%}" if f_cost > 0 else "")
    
    # Save detailed output for inspection
    with open('data/eval/model_comparison_output.json', 'w') as f:
        json.dump(comparison_results, f, indent=2)

if __name__ == "__main__":
    run_comparison()
