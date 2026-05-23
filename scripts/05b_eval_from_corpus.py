"""Re-evaluate NER on the eval set using predictions from the full-corpus run.

The full-corpus run (`06_run_full_corpus.py`) used the raw `inscription` field
with the damage filter active — the input format the production pipeline uses.
Rather than re-running NER on the eval set, this script joins the eval GT
against those existing predictions.

Records skipped by the corpus damage filter (134/433 eval records) are counted
as `fn_damaged` — unrecoverable from the raw text, same accounting as already-
damaged GT names within an inscription.

Praenomen post-process from `06_export_to_dataset.py` is applied to predictions
before scoring, so the F1 reflects the production deliverable.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("export_mod", os.path.join(os.path.dirname(__file__), "06_export_to_dataset.py"))
export_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_mod)
fix_praenomen = export_mod.fix_praenomen

# Reuse the scoring logic from 05_evaluate_ner.py
spec5 = importlib.util.spec_from_file_location("eval_mod", os.path.join(os.path.dirname(__file__), "05_evaluate_ner.py"))
eval_mod = importlib.util.module_from_spec(spec5)
spec5.loader.exec_module(eval_mod)
get_person_signature = eval_mod.get_person_signature
is_imperial = eval_mod.is_imperial
is_imperial_inscription = eval_mod.is_imperial_inscription
is_damaged = eval_mod.is_damaged
names_match = eval_mod.names_match

from name_filters import classify_non_person_fp


def apply_praenomen_fix(persons):
    """Apply the same praenomen rotation that the export script uses."""
    fixed = []
    for p in persons:
        new_p = dict(p)
        pr, no, co = fix_praenomen(new_p.get('praenomen'), new_p.get('nomen'), new_p.get('cognomen'))
        new_p['praenomen'] = pr
        new_p['nomen'] = no
        new_p['cognomen'] = co
        fixed.append(new_p)
    return fixed


def main():
    eval_path = 'data/eval/africa_proconsularis_eval.jsonl'
    corpus_path = 'data/output/africa_proconsularis_ner_full.jsonl'

    # Load corpus predictions keyed by ID
    corpus_preds = {}
    with open(corpus_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            corpus_preds[r['id']] = r.get('persons', [])

    # Load eval set
    eval_records = []
    with open(eval_path, 'r', encoding='utf-8') as f:
        for line in f:
            eval_records.append(json.loads(line))

    tp = 0
    fp_imperial = 0
    fp_deity = 0
    fp_epithet = 0
    fp_other = 0
    fn = 0
    fn_damaged = 0
    fn_filtered = 0  # GT persons in records that the damage filter skipped

    discoveries_other = []
    matched_records = 0
    skipped_records = 0

    for record in eval_records:
        rec_id = record['id']
        text = record.get('text', '')
        ground_truth = record.get('ground_truth_people', [])

        if not isinstance(ground_truth, list):
            gt_pairs = []
        else:
            gt_pairs = [(p, get_person_signature(p)) for p in ground_truth if isinstance(p, dict)]

        # Records the damage filter dropped from the corpus run — count GT as unrecoverable
        if rec_id not in corpus_preds:
            skipped_records += 1
            for p_gt, gt_sig in gt_pairs:
                if gt_sig:
                    fn_filtered += 1
            continue

        matched_records += 1
        predictions = apply_praenomen_fix(corpus_preds[rec_id])
        pred_pairs = [(p, get_person_signature(p)) for p in predictions if isinstance(p, dict)]
        pred_signatures = [sig for _, sig in pred_pairs]

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

        for p_raw, pred_sig in pred_pairs:
            if not pred_sig:
                continue
            if len(p_raw.get('raw_name', '')) <= 1:
                continue
            found = any(names_match(pred_sig, gs) for _, gs in gt_pairs if gs)
            if not found:
                # Old imperial detection (status keywords + inscription-level formulae)
                if is_imperial(p_raw) or is_imperial_inscription(text):
                    fp_imperial += 1
                    continue
                # New: deity / expanded-imperial / bare-epithet classifier
                non_person = classify_non_person_fp(p_raw)
                if non_person == 'imperial':
                    fp_imperial += 1
                elif non_person == 'deity':
                    fp_deity += 1
                elif non_person == 'epithet':
                    fp_epithet += 1
                else:
                    fp_other += 1
                    discoveries_other.append({
                        "id": rec_id,
                        "name": p_raw.get('raw_name', 'Unknown'),
                        "expanded": " ".join(filter(None, [p_raw.get('praenomen'), p_raw.get('nomen'), p_raw.get('cognomen')])),
                        "status": p_raw.get('status'),
                    })

    total_fp = fp_imperial + fp_deity + fp_epithet + fp_other
    # Recall(raw) treats all unanswered GT (damaged + damage-filtered + real miss) as misses.
    # Recall(adjusted) only counts real misses — the honest model-quality measure.
    precision_raw = tp / (tp + total_fp) if (tp + total_fp) > 0 else 0
    precision_adj = tp / (tp + fp_other) if (tp + fp_other) > 0 else 0
    recall_raw = tp / (tp + fn + fn_damaged + fn_filtered) if (tp + fn + fn_damaged + fn_filtered) > 0 else 0
    recall_adj = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1_adj = 2 * (precision_adj * recall_adj) / (precision_adj + recall_adj) if (precision_adj + recall_adj) > 0 else 0

    print("-" * 60)
    print("NER EVALUATION — RAW INSCRIPTION INPUT (from full-corpus run)")
    print("-" * 60)
    print(f"Eval records total:                  {len(eval_records)}")
    print(f"  scored from corpus output:         {matched_records}")
    print(f"  skipped by damage filter (>30%):   {skipped_records}")
    print()
    print(f"True Positives:                      {tp}")
    print(f"False Negatives (damaged GT name):   {fn_damaged}  <- name in lacuna, unrecoverable")
    print(f"False Negatives (damage-filtered):   {fn_filtered}  <- whole inscription dropped")
    print(f"False Negatives (real misses):       {fn}")
    print(f"FP — Imperial:                       {fp_imperial}")
    print(f"FP — Deity / personification:        {fp_deity}")
    print(f"FP — Bare imperial epithet:          {fp_epithet}")
    print(f"Candidate Discoveries (real FPs):    {fp_other}")
    print("-" * 60)
    print(f"Recall (raw, incl. all damage):      {recall_raw:.2f}")
    print(f"Recall (adjusted, excl. damage):     {recall_adj:.2f}")
    print(f"Precision (raw):                     {precision_raw:.2f}")
    print(f"Precision (adj, excl. non-persons):  {precision_adj:.2f}")
    print(f"F1 (adjusted):                       {f1_adj:.2f}")
    print("-" * 60)

    if discoveries_other:
        print(f"\nTOP 10 CANDIDATE DISCOVERIES (after deity/imperial/epithet filters):")
        for d in discoveries_other[:10]:
            print(f"[{d['id']}] {d['name']} -> {d['expanded']} (Status: {d['status']})")


if __name__ == "__main__":
    main()
