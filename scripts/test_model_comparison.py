import os
import json
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

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

SYSTEM_PROMPT = """You are an expert Latin epigrapher specializing in the Roman inscriptions of Africa Proconsularis.
You will be provided with a list of inscriptions, each with a unique ID.
Your task is to perform Named Entity Recognition (NER) on each inscription and extract personal names.

For each person identified:
1. Deconstruct the name into praenomen, nomen, and cognomen.
2. Identify gender ('male', 'female', or 'unknown') and social/professional status markers.
3. Handle Abbreviations: Expand standard abbreviations (e.g., 'L.' to 'Lucius', 'M.' to 'Marcus', 'f.' to 'filius').
4. Return a JSON object containing a 'results' list, where each item matches an ID to its extracted persons list."""

def run_test(model_name, records, thinking=True):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    batch_input = [{"id": r["id"], "text": r["text"]} for r in records]
    config = {
        "system_instruction": SYSTEM_PROMPT,
        "response_mime_type": "application/json",
        "response_schema": BatchNEROutput,
    }
    if not thinking:
        config["thinking_config"] = {"thinking_budget": 0}
    response = client.models.generate_content(
        model=model_name,
        contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
        config=config,
    )
    return {r.id: r.persons for r in response.parsed.results}

def main():
    with open("data/eval/africa_proconsularis_dev.jsonl") as f:
        records = [json.loads(l) for l in f][:10]

    print(f"Running test on {len(records)} records...\n")

    print("=" * 60)
    print("MODEL: gemini-2.5-flash (thinking disabled)")
    print("=" * 60)
    results_fast = run_test("gemini-2.5-flash", records, thinking=False)

    for r in records:
        pred = results_fast.get(r["id"], [])
        gt = r["ground_truth_people"]
        gt_names = [" ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen")])) for p in gt]
        pred_names = [" ".join(filter(None, [p.praenomen, p.nomen, p.cognomen])) for p in pred]
        print(f"\n[{r['id']}]")
        print(f"  Text: {r['text'][:80]}...")
        print(f"  GT:   {gt_names}")
        print(f"  Pred: {pred_names}")

if __name__ == "__main__":
    main()
