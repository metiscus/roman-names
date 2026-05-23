import json
import random
import os

def generate_validation_set():
    input_file = 'data/LIRE_v1-2.geojson'
    output_dir = 'data/eval'
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Loading {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data['features']
    print(f"Total features: {len(features)}")
    
    # Filter for Africa proconsularis with people data
    # Priority: clean_text_interpretive_word_EDCS, then clean_text_interpretive_word, then inscription
    pool = []
    for feat in features:
        props = feat['properties']
        people_data = props.get('people')
        
        # Strictly require a valid list of people to ensure dense ground truth
        if props.get('province') == 'Africa proconsularis' and isinstance(people_data, list) and len(people_data) > 0:
            # Determine best text field
            text = props.get('clean_text_interpretive_word_EDCS') or \
                   props.get('clean_text_interpretive_word') or \
                   props.get('inscription')
            
            if text and len(text.strip()) > 0:
                pool.append({
                    'id': props.get('EDCS-ID') or props.get('EDH-ID'),
                    'text': text.strip(),
                    'ground_truth_people': props['people']
                })
    
    print(f"Filtered pool size (Africa proconsularis with people): {len(pool)}")
    
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
    dev_path = os.path.join(output_dir, 'africa_proconsularis_dev.jsonl')
    eval_path = os.path.join(output_dir, 'africa_proconsularis_eval.jsonl')
    
    with open(dev_path, 'w', encoding='utf-8') as f:
        for item in dev_set:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    with open(eval_path, 'w', encoding='utf-8') as f:
        for item in eval_set:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"Saved {len(dev_set)} records to {dev_path}")
    print(f"Saved {len(eval_set)} records to {eval_path}")

if __name__ == "__main__":
    generate_validation_set()
