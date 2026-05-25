"""Generate a triage CSV of candidate discoveries for manual review.

Replays the same join 05b_eval_from_corpus.py does to identify the candidate
discoveries (eval-set predictions that don't match LIRE GT and aren't classified
as deity/imperial/epithet). Adds the raw EDCS inscription text to each row so a
reviewer can judge from context without leaving the spreadsheet.

Output: data/triage_candidates.csv

Columns:
- edcs_id, edcs_url               source pointer
- raw_inscription                 what the model saw (with lacuna markers)
- raw_name                        what the model extracted from that inscription
- praenomen, nomen, cognomen      structured parse
- gender, status                  model-inferred attributes
- fragmentary                     model's own fragmentary flag
- evidence_score                  triage priority (see compute_evidence_score)
- verdict, identified_as, notes   blank, for the reviewer to fill in
"""
import json
import csv
import os
import sys
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import EDCS_PATH, EVAL_DIR, OUTPUT_DIR

# Reuse export + eval modules
spec = importlib.util.spec_from_file_location("export_mod", os.path.join(os.path.dirname(__file__), "06_export_to_dataset.py"))
export_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(export_mod)
fix_praenomen = export_mod.fix_praenomen

spec5 = importlib.util.spec_from_file_location("eval_mod", os.path.join(os.path.dirname(__file__), "05_evaluate_ner.py"))
eval_mod = importlib.util.module_from_spec(spec5); spec5.loader.exec_module(eval_mod)
get_person_signature = eval_mod.get_person_signature
is_imperial = eval_mod.is_imperial
is_imperial_inscription = eval_mod.is_imperial_inscription
names_match = eval_mod.names_match

from name_filters import classify_non_person_fp


EDCS_URL_TEMPLATE = "https://db.edcs.eu/epigr/epi_single.php?p_edcs_id={}"


def compute_evidence_score(person):
    """Higher score = more likely to be a real person worth triaging first.

    Heuristic: a populated status field is the strongest signal (a specific
    magistracy or rank rarely shows up on a damaged fragment). A full triple
    of praenomen+nomen+cognomen is the next strongest. Fragmentary flag and
    very-short raw_name pull the score down.
    """
    score = 0
    if person.get('status'):
        score += 3
    if person.get('praenomen'):
        score += 1
    if person.get('nomen'):
        score += 1
    if person.get('cognomen'):
        score += 1
    raw = person.get('raw_name') or ''
    if len(raw) >= 20:
        score += 1
    if person.get('fragmentary'):
        score -= 2
    return score


def main(province='africa_proconsularis'):
    eval_path = EVAL_DIR / f'{province}_eval.jsonl'
    corpus_path = OUTPUT_DIR / f'{province}_ner_full.jsonl'
    edcs_path = EDCS_PATH
    output_path = f'data/triage_candidates_{province}.csv'

    print(f"Loading EDCS for raw-inscription join...")
    with open(edcs_path) as f:
        edcs_data = json.load(f)
    edcs_text = {r['EDCS-ID']: (r.get('inscription') or r.get('clean_text_interpretive_word') or '')
                 for r in edcs_data if r.get('EDCS-ID')}

    print(f"Loading corpus predictions...")
    corpus_preds = {}
    with open(corpus_path) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                corpus_preds[r['id']] = r.get('persons', [])

    print(f"Loading eval ground truth...")
    eval_records = []
    with open(eval_path) as f:
        for line in f:
            eval_records.append(json.loads(line))

    candidates = []
    for record in eval_records:
        rec_id = record['id']
        if rec_id not in corpus_preds:
            continue  # damage-filtered, no predictions to triage

        text = record.get('text', '')
        ground_truth = record.get('ground_truth_people', []) or []
        gt_pairs = [(p, get_person_signature(p)) for p in ground_truth if isinstance(p, dict)]

        # Apply praenomen fix to predictions (same as export does)
        preds = []
        for p in corpus_preds[rec_id]:
            np = dict(p)
            pr, no, co = fix_praenomen(np.get('praenomen'), np.get('nomen'), np.get('cognomen'))
            np['praenomen'] = pr; np['nomen'] = no; np['cognomen'] = co
            preds.append(np)

        pred_pairs = [(p, get_person_signature(p)) for p in preds if isinstance(p, dict)]

        for p_raw, pred_sig in pred_pairs:
            if not pred_sig or len(p_raw.get('raw_name', '')) <= 1:
                continue
            # Skip true positives (matched against LIRE GT)
            if any(names_match(pred_sig, gs) for _, gs in gt_pairs if gs):
                continue
            # Skip non-person FPs (old imperial + new deity/imperial/epithet)
            if is_imperial(p_raw) or is_imperial_inscription(text):
                continue
            if classify_non_person_fp(p_raw):
                continue
            candidates.append({
                'edcs_id': rec_id,
                'edcs_url': EDCS_URL_TEMPLATE.format(rec_id),
                'raw_inscription': edcs_text.get(rec_id, ''),
                'raw_name': p_raw.get('raw_name') or '',
                'praenomen': p_raw.get('praenomen') or '',
                'nomen': p_raw.get('nomen') or '',
                'cognomen': p_raw.get('cognomen') or '',
                'gender': p_raw.get('gender') or '',
                'status': p_raw.get('status') or '',
                'fragmentary': p_raw.get('fragmentary', False),
                'evidence_score': compute_evidence_score(p_raw),
                'verdict': '',
                'identified_as': '',
                'notes': '',
            })

    # Triage best-evidence-first
    candidates.sort(key=lambda c: (-c['evidence_score'], c['edcs_id']))

    fieldnames = ['edcs_id', 'edcs_url', 'raw_inscription', 'raw_name',
                  'praenomen', 'nomen', 'cognomen', 'gender', 'status',
                  'fragmentary', 'evidence_score',
                  'verdict', 'identified_as', 'notes']

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(candidates)

    print(f"\nWrote {len(candidates)} candidates to {output_path}")
    print()
    print("Evidence-score distribution:")
    from collections import Counter
    for score, n in sorted(Counter(c['evidence_score'] for c in candidates).items(), reverse=True):
        print(f"  score {score:+d}: {n}")
    print()
    print("Top 5 (highest evidence — start here):")
    for c in candidates[:5]:
        print(f"  [{c['edcs_id']}] score={c['evidence_score']} raw={c['raw_name']!r}")
        if c['status']:
            print(f"      status: {c['status']}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--province', default='africa_proconsularis',
                        help='Province slug matching the eval/corpus filename prefix')
    args = parser.parse_args()
    main(province=args.province)
