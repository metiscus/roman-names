import json
import re

# Standard Latin praenomen abbreviations used in epigraphic databases (LIRE, EDCS)
PRAENOMEN_EXPANSIONS = {
    'a.': 'aulus', 'ap.': 'appius', 'c.': 'gaius', 'cn.': 'gnaeus',
    'd.': 'decimus', 'k.': 'kaeso', 'l.': 'lucius', 'm.': 'marcus',
    "m'.": 'manius', 'mam.': 'mamercus', 'n.': 'numerius', 'p.': 'publius',
    'q.': 'quintus', 'sex.': 'sextus', 'ser.': 'servius', 'sp.': 'spurius',
    't.': 'titus', 'ti.': 'tiberius', 'v.': 'vibius',
}

IMPERIAL_KEYWORDS = {'emperor', 'divus', 'caesar', 'augustus', 'augusta', 'imperator'}
IMPERIAL_FORMULAE = ('imperatori', 'imperator ', 'imp. caes', 'imp caes', 'domino nostro', 'divo ', 'divae ')

def normalize(text):
    if not text:
        return ""
    text = re.sub(r'[\+\!\*\[\]\(\)\/]', '', text)
    return text.strip().lower()

def get_person_signature(p):
    praenomen = p.get('praenomen') or ''
    praenomen_normalized = PRAENOMEN_EXPANSIONS.get(praenomen.strip().lower(), praenomen)
    components = [praenomen_normalized, p.get('nomen') or '', p.get('cognomen') or '']
    return normalize(" ".join([c for c in components if c]))

def is_imperial(p):
    status = (p.get('status') or '').lower()
    return any(kw in status for kw in IMPERIAL_KEYWORDS)

def is_imperial_inscription(text):
    return text.strip().lower().startswith(IMPERIAL_FORMULAE)

def is_damaged(p):
    raw = p.get('name', '')
    return '[' in raw or '+' in raw or '*' in raw

def names_match(sig_a, sig_b, threshold=0.75):
    """Word-overlap match with 6-char prefix comparison to handle Latin case endings."""
    words_a = sig_a.split()
    words_b = sig_b.split()
    if not words_a or not words_b:
        return False
    # Use the shorter sig as the query to avoid penalising extra cognomina
    query, target = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    matched = sum(1 for w in query if any(w[:6] == t[:6] for t in target))
    return matched / len(query) >= threshold

def evaluate_ner():
    input_path = 'data/eval/ner_results_500_batched.json'
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            results = json.load(f)
    except FileNotFoundError:
        print(f"Error: {input_path} not found. Run the extraction script first.")
        return

    tp = 0
    fp_imperial = 0
    fp_other = 0
    fn = 0
    fn_damaged = 0

    discoveries_other = []

    print(f"Evaluating {len(results)} records...")

    for record in results:
        ground_truth = record['ground_truth']
        predictions = record['prediction']
        text = record['text']

        if not isinstance(ground_truth, list):
            gt_pairs = []
        else:
            gt_pairs = [(p, get_person_signature(p)) for p in ground_truth if isinstance(p, dict)]

        pred_pairs = [(p, get_person_signature(p)) for p in predictions if isinstance(p, dict)]
        pred_signatures = [sig for _, sig in pred_pairs]

        # Recall check
        for p_gt, gt_sig in gt_pairs:
            if not gt_sig:
                continue
            found = any(names_match(gt_sig, ps) for ps in pred_signatures if ps)
            if found:
                tp += 1
            elif is_damaged(p_gt):
                fn_damaged += 1
            else:
                fn += 1

        # Precision check
        for p_raw, pred_sig in pred_pairs:
            if not pred_sig: continue
            if len(p_raw.get('raw_name', '')) <= 1: continue
            found = any(names_match(pred_sig, gs) for _, gs in gt_pairs if gs)
            if not found:
                if is_imperial(p_raw) or is_imperial_inscription(text):
                    fp_imperial += 1
                else:
                    fp_other += 1
                    discoveries_other.append({
                        "id": record['id'],
                        "name": p_raw.get('raw_name', 'Unknown'),
                        "expanded": " ".join(filter(None, [p_raw.get('praenomen'), p_raw.get('nomen'), p_raw.get('cognomen')])),
                        "status": p_raw.get('status'),
                    })

    total_fp = fp_imperial + fp_other
    precision_raw = tp / (tp + total_fp) if (tp + total_fp) > 0 else 0
    precision_adj = tp / (tp + fp_other) if (tp + fp_other) > 0 else 0
    recall_raw = tp / (tp + fn + fn_damaged) if (tp + fn + fn_damaged) > 0 else 0
    recall_adj = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1_adj = 2 * (precision_adj * recall_adj) / (precision_adj + recall_adj) if (precision_adj + recall_adj) > 0 else 0

    print("-" * 40)
    print("NER EVALUATION SUMMARY")
    print("-" * 40)
    print(f"True Positives:                  {tp}")
    print(f"False Negatives (damaged text):  {fn_damaged}  <- unanswerable from text alone")
    print(f"False Negatives (real misses):   {fn}")
    print(f"Imperial filtered out:           {fp_imperial}")
    print(f"Other Discoveries (potential):   {fp_other}")
    print("-" * 40)
    print(f"Recall (raw, incl. damaged):     {recall_raw:.2f}")
    print(f"Recall (adjusted, excl. damaged):{recall_adj:.2f}")
    print(f"Precision (raw):                 {precision_raw:.2f}")
    print(f"Precision (adjusted):            {precision_adj:.2f}")
    print(f"F1 (adjusted):                   {f1_adj:.2f}")
    print("-" * 40)

    if discoveries_other:
        print("\nTOP 10 POTENTIAL DISCOVERIES (Non-Imperial, Undamaged):")
        for d in discoveries_other[:10]:
            print(f"[{d['id']}] {d['name']} -> {d['expanded']} (Status: {d['status']})")

if __name__ == "__main__":
    evaluate_ner()
