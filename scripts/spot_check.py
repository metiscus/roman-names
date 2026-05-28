"""Spot-check NER output for AI or human review between supervised run segments.

Usage:
    python3 scripts/spot_check.py --province dalmatia --n 50
    python3 scripts/spot_check.py --province dalmatia --n 50 --recent
    python3 scripts/spot_check.py --province dalmatia --n 50 --with-gt

Prints a compact, readable summary of sampled records: inscription text,
extracted persons, and (with --with-gt) the LIRE ground truth where available.
Designed to be piped into an LLM for quality review.
"""
import json
import os
import re
import random
import argparse
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import EDCS_PATH, LIRE_PATH, OUTPUT_DIR

DAMAGE_THRESHOLD = 0.30

def damage_ratio(text):
    stripped = re.sub(r'\[[^\]]*\]', '', text)
    return (len(text) - len(stripped)) / len(text) if text else 1.0

def load_corpus_output(province_slug):
    path = OUTPUT_DIR / f'{province_slug}_ner_full.jsonl'
    if not os.path.exists(path):
        print(f"No corpus output found at {path}. Run 06_run_full_corpus.py first.")
        sys.exit(1)
    records = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def load_source_texts(province_name):
    with open(EDCS_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return {r['EDCS-ID']: r.get('inscription') or r.get('clean_text_interpretive_word', '')
            for r in data if r.get('province') == province_name}

def load_lire_gt(province_name):
    """Return dict of EDCS-ID → people list for records with ground truth."""
    gt = {}
    with open(LIRE_PATH, encoding='utf-8') as f:
        lire = json.load(f)
    for feat in lire['features']:
        p = feat['properties']
        if (p.get('province') == province_name
                and isinstance(p.get('people'), list)
                and len(p['people']) > 0
                and p.get('EDCS-ID')):
            gt[p['EDCS-ID']] = p['people']
    return gt

def format_person(p):
    parts = [x for x in [p.get('praenomen'), p.get('nomen'), p.get('cognomen')] if x]
    name = ' '.join(parts) or p.get('raw_name', '?')
    extras = []
    if p.get('gender') and p['gender'] != 'unknown':
        extras.append(p['gender'])
    if p.get('status'):
        extras.append(p['status'])
    if p.get('fragmentary'):
        extras.append('FRAG')
    suffix = f" [{', '.join(extras)}]" if extras else ''
    return f"  • {name}{suffix}  (raw: {p.get('raw_name', '')})"

def format_gt_person(p):
    parts = [x for x in [p.get('praenomen'), p.get('nomen'), p.get('cognomen')] if x]
    name = ' '.join(parts) or p.get('name', '?')
    status = f" [{p['status']}]" if p.get('status') else ''
    return f"  ✓ {name}{status}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--province', required=True,
                        help='Province slug (e.g. dalmatia) or full name (e.g. "Dalmatia")')
    parser.add_argument('--n', type=int, default=50, help='Number of records to sample')
    parser.add_argument('--recent', action='store_true',
                        help='Sample from the most recently processed records (tail of output file)')
    parser.add_argument('--with-gt', action='store_true',
                        help='Show LIRE ground truth alongside predictions where available')
    parser.add_argument('--only-persons', action='store_true',
                        help='Skip records where no persons were extracted')
    parser.add_argument('--seed', type=int, default=None, help='Random seed for reproducibility')
    args = parser.parse_args()

    # Normalise province slug vs display name
    if ' ' in args.province or args.province[0].isupper():
        province_name = args.province
        province_slug = args.province.lower().replace(' ', '_')
    else:
        province_slug = args.province
        # Use replace+capitalize per word but preserve original case of first char
        # to match EDCS storage (e.g. "Pannonia superior" not "Pannonia Superior")
        words = args.province.replace('_', ' ').split()
        province_name = words[0].capitalize() + (' ' + ' '.join(w.lower() for w in words[1:]) if len(words) > 1 else '')

    records = load_corpus_output(province_slug)
    texts = load_source_texts(province_name)
    gt = load_lire_gt(province_name) if args.with_gt else {}

    if args.only_persons:
        records = [r for r in records if r.get('persons')]

    if args.recent:
        sample = records[-args.n:]
    else:
        rng = random.Random(args.seed)
        sample = rng.sample(records, min(args.n, len(records)))

    print(f"=== SPOT CHECK: {province_name} ===")
    print(f"Total processed: {len(records)} | Sampling: {len(sample)}")
    if args.with_gt:
        gt_overlap = sum(1 for r in records if r['id'] in gt)
        print(f"LIRE GT available for: {gt_overlap} / {len(records)} records")
    print()

    for i, rec in enumerate(sample, 1):
        rec_id = rec['id']
        text = texts.get(rec_id, '[text not found]')
        persons = rec.get('persons', [])
        gt_persons = gt.get(rec_id, []) if args.with_gt else []

        print(f"--- [{i}/{len(sample)}] {rec_id} ---")
        print(f"TEXT: {text[:200]}{'...' if len(text) > 200 else ''}")

        if persons:
            print("EXTRACTED:")
            for p in persons:
                print(format_person(p))
        else:
            print("EXTRACTED: (none)")

        if args.with_gt and gt_persons:
            print("GROUND TRUTH (LIRE):")
            for p in gt_persons:
                print(format_gt_person(p))
        elif args.with_gt and rec_id in gt:
            print("GROUND TRUTH (LIRE): (empty list)")

        print()

    # Summary stats
    total_persons = sum(len(r.get('persons', [])) for r in sample)
    empty_records = sum(1 for r in sample if not r.get('persons'))
    print(f"=== SUMMARY ===")
    print(f"Records sampled:       {len(sample)}")
    print(f"Records with 0 people: {empty_records} ({empty_records/len(sample):.0%})")
    print(f"Total persons extracted: {total_persons} ({total_persons/len(sample):.1f} per record)")
    if args.with_gt:
        gt_in_sample = [r for r in sample if r['id'] in gt]
        print(f"Records with GT in sample: {len(gt_in_sample)}")

if __name__ == '__main__':
    main()
