"""
NER regression test suite.

Runs all test cases in regression_tests.jsonl against the model and checks that
the output matches the expected values. Use this to catch prompt regressions when
the model or prompt changes.

Usage:
    python3 scripts/run_regression.py
    python3 scripts/run_regression.py --model gemini-2.5-flash-lite
    python3 scripts/run_regression.py --filter R08,R09,R10    # run specific cases
    python3 scripts/run_regression.py --verbose               # show full output
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prompt_utils import get_system_prompt
from config import REPO_ROOT
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional

load_dotenv()

TESTS_PATH = REPO_ROOT / "scripts" / "regression_tests.jsonl"

CANONICAL_PRAENOMINA = {
    'Gaius', 'Caius', 'Lucius', 'Marcus', 'Publius', 'Quintus', 'Titus', 'Aulus',
    'Gnaeus', 'Sextus', 'Spurius', 'Manius', 'Servius', 'Appius', 'Decimus',
    'Tiberius', 'Numerius', 'Kaeso', 'Vibius',
}

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


def norm(s):
    """Normalize a name for comparison: lowercase, strip, Gaius↔Caius."""
    if s is None:
        return None
    s = s.strip().lower()
    return s.replace('caius', 'gaius').replace('kaeso', 'caeso')


def check_person(predicted: dict, expected: dict) -> list[str]:
    """Return list of failure strings for this expected person spec."""
    failures = []

    for field in ('praenomen', 'nomen', 'cognomen', 'gender'):
        if field not in expected:
            continue
        exp_val = expected[field]
        pred_val = predicted.get(field)
        if exp_val is None:
            if pred_val is not None:
                failures.append(f"{field}: expected null, got '{pred_val}'")
        else:
            if pred_val is None:
                failures.append(f"{field}: expected '{exp_val}', got null")
            elif norm(pred_val) != norm(exp_val):
                failures.append(f"{field}: expected '{exp_val}', got '{pred_val}'")

    # Substring checks
    for key in ('cognomen_contains', 'status_contains'):
        if key not in expected:
            continue
        field = key.replace('_contains', '')
        pred_val = (predicted.get(field) or '').lower()
        exp_substr = expected[key].lower()
        if exp_substr not in pred_val:
            failures.append(f"{field}: expected to contain '{expected[key]}', got '{predicted.get(field)}'")

    # Placement-agnostic name check: the expanded form must appear in SOME name
    # field (praenomen/nomen/cognomen). Use when downstream export normalizes the
    # field — e.g. a nomen the model intermittently files under praenomen.
    if 'name_contains' in expected:
        joined = ' '.join((norm(predicted.get(f)) or '') for f in ('praenomen', 'nomen', 'cognomen'))
        sub = norm(expected['name_contains'])
        if sub and sub not in joined:
            failures.append(f"name: expected some name field to contain '{expected['name_contains']}', got '{joined.strip()}'")

    if 'fragmentary' in expected:
        pred_frag = predicted.get('fragmentary', False)
        if pred_frag != expected['fragmentary']:
            failures.append(f"fragmentary: expected {expected['fragmentary']}, got {pred_frag}")

    return failures


def match_persons(predicted_persons: list, expected_persons: list) -> list[tuple]:
    """
    For each expected person spec, find the best-matching predicted person.
    Returns list of (expected_spec, best_predicted_dict, failures).
    """
    used = set()
    results = []
    for exp in expected_persons:
        best_match = None
        best_failures = None
        for i, pred in enumerate(predicted_persons):
            if i in used:
                continue
            failures = check_person(pred, exp)
            if best_failures is None or len(failures) < len(best_failures):
                best_failures = failures
                best_match = (i, pred)
        if best_match is not None:
            used.add(best_match[0])
            results.append((exp, best_match[1], best_failures))
        else:
            results.append((exp, None, ['no matching person found']))
    return results


def run_tests(model: str, filter_ids: list[str] | None, verbose: bool):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Load test cases
    tests = []
    with open(TESTS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                tests.append(json.loads(line))

    if filter_ids:
        tests = [t for t in tests if t['id'] in filter_ids]
        if not tests:
            print(f"No tests matched filter: {filter_ids}")
            sys.exit(1)

    print(f"Running {len(tests)} regression tests against {model}\n")

    # Group by province for batching (keeps the prompt consistent)
    from collections import defaultdict
    by_province = defaultdict(list)
    for t in tests:
        by_province[t['province']].append(t)

    all_results = {}  # id → predicted persons list
    for province, province_tests in by_province.items():
        batch_input = [{'id': t['id'], 'text': t['input']} for t in province_tests]
        system_prompt = get_system_prompt(province)
        backoff = 5
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=f"Please process this batch of inscriptions: {json.dumps(batch_input, ensure_ascii=False)}",
                    config={
                        'system_instruction': system_prompt,
                        'response_mime_type': 'application/json',
                        'response_schema': BatchNEROutput,
                        'thinking_config': {'thinking_budget': 0},
                    },
                )
                if response.parsed:
                    for result in response.parsed.results:
                        all_results[result.id] = [p.model_dump() for p in result.persons]
                else:
                    for t in province_tests:
                        all_results[t['id']] = None
                break
            except Exception as e:
                err_str = str(e)
                if '503' in err_str or '429' in err_str or 'quota' in err_str.lower() or 'UNAVAILABLE' in err_str:
                    print(f"  RETRY ({attempt+1}/4) for province '{province}': {err_str[:80]}")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                print(f"  ERROR calling model for province '{province}': {e}")
                for t in province_tests:
                    all_results[t['id']] = None
                break
        else:
            print(f"  ERROR: max retries exceeded for province '{province}'")
            for t in province_tests:
                all_results[t['id']] = None

    # Score
    passed = 0
    failed = 0
    failed_cases = []

    for test in tests:
        tid = test['id']
        desc = test['description']
        exp = test['expected']
        predicted = all_results.get(tid)

        test_failures = []

        if predicted is None:
            test_failures.append("model returned null/error")
        else:
            # Person count checks
            if 'person_count' in exp:
                if len(predicted) != exp['person_count']:
                    test_failures.append(
                        f"person_count: expected {exp['person_count']}, got {len(predicted)}"
                    )
            if 'min_persons' in exp:
                if len(predicted) < exp['min_persons']:
                    test_failures.append(
                        f"min_persons: expected ≥{exp['min_persons']}, got {len(predicted)}"
                    )

            # Per-person field checks
            if 'persons' in exp and predicted:
                matches = match_persons(predicted, exp['persons'])
                for exp_spec, pred_person, person_failures in matches:
                    for f in person_failures:
                        test_failures.append(f)

        status = "PASS" if not test_failures else "FAIL"
        if not test_failures:
            passed += 1
            marker = "✓"
        else:
            failed += 1
            marker = "✗"
            failed_cases.append((test, test_failures, predicted))

        print(f"  {marker} [{tid}] {test['category']}: {desc[:60]}")
        if test_failures and verbose:
            for f in test_failures:
                print(f"        ↳ {f}")
        if verbose and predicted is not None:
            print(f"        predicted: {json.dumps(predicted, ensure_ascii=False)[:200]}")

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{passed+failed} passed")
    if failed_cases:
        print(f"\nFailed cases:")
        for test, failures, predicted in failed_cases:
            print(f"\n  [{test['id']}] {test['description']}")
            for f in failures:
                print(f"    - {f}")
            if predicted is not None:
                print(f"    predicted: {json.dumps(predicted, ensure_ascii=False)[:300]}")
    print()
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Run NER regression tests.")
    parser.add_argument("--model", default="gemini-2.5-flash-lite",
                        help="Gemini model to test (default: gemini-2.5-flash-lite)")
    parser.add_argument("--filter", type=str, default=None,
                        help="Comma-separated list of test IDs to run (e.g. R08,R09)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show full predicted output for each test")
    args = parser.parse_args()

    filter_ids = [x.strip() for x in args.filter.split(',')] if args.filter else None
    ok = run_tests(args.model, filter_ids, args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
