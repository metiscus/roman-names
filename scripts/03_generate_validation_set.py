import json
import random
import os
import sys
import argparse
import ast
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LIRE_PATH, EVAL_DIR


def parse_people(value):
    """Return a list of person dicts from a LIRE `people` field.

    v1.2 stored a real list. v3.0 stores a *stringified* numpy/pandas repr of
    the list (single quotes, None, dicts separated by newlines with no commas) —
    or an empty list `[]` when there are no people. Without this, the eval-set
    builder reads zero people from v3.0 for every province.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s or s == '[]':
            return []
        # numpy dropped the commas between dict elements — put them back.
        s = re.sub(r'\}\s*\n\s*\{', '}, {', s)
        try:
            parsed = ast.literal_eval(s)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []
    return []


def generate_validation_set(province):
    input_file = LIRE_PATH
    output_dir = EVAL_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    # Standardize filename format
    safe_name = re.sub(r'[()]', '', province).lower().replace(' ', '_')
    dev_path = os.path.join(output_dir, f'{safe_name}_dev.jsonl')
    eval_path = os.path.join(output_dir, f'{safe_name}_eval.jsonl')

    print(f"Loading {input_file} for province '{province}'...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data['features']
    print(f"Total features in LIRE: {len(features)}")
    
    pool = []
    for feat in features:
        props = feat['properties']
        if props.get('province') != province:
            continue
        people_data = parse_people(props.get('people'))

        # Strictly require people to ensure dense ground truth
        if len(people_data) > 0:
            # Determine best text field
            text = props.get('clean_text_interpretive_word_EDCS') or \
                   props.get('clean_text_interpretive_word') or \
                   props.get('inscription')

            if text and len(text.strip()) > 0:
                pool.append({
                    'id': props.get('EDCS-ID') or props.get('EDH-ID'),
                    'text': text.strip(),
                    'ground_truth_people': people_data
                })
    
    print(f"Filtered pool size ({province} with people): {len(pool)}")
    
    if len(pool) == 0:
        print(f"Error: No records found for province '{province}'.")
        return

    if len(pool) < 550:
        print(f"Warning: Pool size {len(pool)} is less than the requested 550. Sampling all available.")
        random.shuffle(pool)
        dev_set = pool[:min(50, len(pool))]
        eval_set = pool[min(50, len(pool)):]
    else:
        # Shuffle and sample
        random.seed(42) # Reproducibility
        random.shuffle(pool)
        dev_set = pool[:50]
        eval_set = pool[50:550]
    
    # Write JSONL files
    with open(dev_path, 'w', encoding='utf-8') as f:
        for item in dev_set:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    with open(eval_path, 'w', encoding='utf-8') as f:
        for item in eval_set:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"Saved {len(dev_set)} records to {dev_path}")
    print(f"Saved {len(eval_set)} records to {eval_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate validation set from LIRE for a specific province.")
    parser.add_argument("--province", type=str, default="Africa proconsularis", help="The province name (e.g. 'Britannia', 'Aegyptus')")
    args = parser.parse_args()
    
    generate_validation_set(args.province)
