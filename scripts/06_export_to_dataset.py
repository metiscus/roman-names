import json
import pandas as pd
import sys
from tqdm import tqdm
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from name_filters import is_deity, is_imperial_person, is_bare_epithet, is_place
from config import EDCS_PATH, LIRE_PATH, OUTPUT_DIR

_LOOKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lookup')


def _load_lookup(filename):
    """Load a one-token-per-line text file, preserving original case."""
    path = os.path.join(_LOOKUP_DIR, filename)
    result = set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if line:
                result.add(line)
    return result


# Canonical Latin praenomina. Anything else in the praenomen field is a
# misclassification (most often a nomen like Flavius/Iulius the model anchored
# positionally) and gets rotated left at export time.
CANONICAL_PRAENOMINA = _load_lookup('praenomina_canonical.txt')


def fix_praenomen(praenomen, nomen, cognomen):
    """Rotate left if praenomen is off-whitelist (model misclassification).

    Returns (praenomen, nomen, cognomen). The mid-run audit found ~0.5% of
    persons had a nomen (Fl./Iun./Iul./Fab. etc.) filed in the praenomen
    field due to positional anchoring overriding the prompt rule.
    """
    if praenomen is None or praenomen in CANONICAL_PRAENOMINA:
        return praenomen, nomen, cognomen

    new_nomen = praenomen
    parts = [p for p in (nomen, cognomen) if p]
    new_cognomen = ' '.join(parts) if parts else None
    return None, new_nomen, new_cognomen


# Cognomina genuinely nominative in -o (3rd decl, genitive -onis) — never
# "corrected", in case one is misfiled into the nomen field. Mirrors the prompt's
# CASE NORMALIZATION carve-out.
_NOMINATIVE_O_NAMES = {'cato', 'fronto', 'hilario', 'pantaleo', 'naso', 'scipio',
                       'varro', 'cicero', 'nero', 'pollio', 'milo'}


def fix_nomen_case(nomen):
    """Deterministically convert an oblique-case nomen to the nominative.

    A Roman nomen (gentilicium) is 2nd-declension and is essentially never
    nominative in -o or -ii; those endings are a dative (-o) or genitive (-ii)
    the model failed to decline. The conversion is unambiguous:
        dative   -o  -> -us   (Iulio->Iulius, Geminio->Geminius, Magno->Magnus)
        genitive -ii -> -ius  (Iulii->Iulius, Flavii->Flavius)
    Single -i genitives are LEFT ALONE — ambiguous between -us and -ius
    (Aviani->Avianus vs Gargili->Gargilius). Cognomina are never passed here, so
    valid -o nominatives like Cato/Scipio are safe (and double-guarded above).
    """
    if not isinstance(nomen, str):
        return nomen
    n = nomen.strip()
    if not n.isalpha() or len(n) < 3 or n.lower() in _NOMINATIVE_O_NAMES:
        return nomen
    low = n.lower()
    if low.endswith('ii'):
        return n[:-2] + 'ius'
    if low.endswith('o'):
        return n[:-1] + 'us'
    return nomen


def create_final_dataset(province_slug='africa_proconsularis', province_name='Africa proconsularis'):
    # 1. Load the big NER results (JSONL format)
    input_ner_path = OUTPUT_DIR / f'{province_slug}_ner_full.jsonl'
    output_parquet = f'data/roman_names_{province_slug}.parquet'
    output_csv = f'data/roman_names_{province_slug}.csv'

    if not os.path.exists(input_ner_path):
        print(f"Error: {input_ner_path} not found.")
        return

    print(f"Loading NER results from {input_ner_path}...")
    ner_results = []
    with open(input_ner_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                ner_results.append(json.loads(line))

    # 2. Load metadata from LIRE (preferred — has coordinates) and EDCS (fallback — covers all)
    print("Loading LIRE metadata for join...")
    with open(LIRE_PATH, 'r', encoding='utf-8') as f:
        lire_data = json.load(f)

    meta_map = {}
    for feat in lire_data['features']:
        props = feat['properties']
        eid = props.get('EDCS-ID')
        if eid:
            meta_map[eid] = {
                'findspot': props.get('place'),
                'latitude': props.get('Latitude'),
                'longitude': props.get('Longitude'),
                'date_from': props.get('dating from'),
                'date_to': props.get('dating to'),
                'inscription_type': props.get('inscr_type'),
                'raw_text': props.get('inscription')
            }

    print("Loading EDCS metadata for fallback join (place + text for non-LIRE records)...")
    with open(EDCS_PATH, 'r', encoding='utf-8') as f:
        edcs_data = json.load(f)

    empty_meta = {'findspot': None, 'latitude': None, 'longitude': None,
                  'date_from': None, 'date_to': None, 'inscription_type': None, 'raw_text': None}
    edcs_lookup = {r['EDCS-ID']: r for r in edcs_data if r.get('EDCS-ID')}

    # 3. Flatten and Join
    print(f"Flattening {len(ner_results)} records into name attestations...")
    rows = []
    praenomen_fixes = 0
    nomen_fixes = 0
    for record in tqdm(ner_results):
        meta = dict(meta_map.get(record['id'], empty_meta))
        # Fall back to EDCS for the ~80% of records not in LIRE
        edcs_r = edcs_lookup.get(record['id'])
        if edcs_r:
            if not meta.get('findspot'):
                meta['findspot'] = edcs_r.get('place')
            if not meta.get('raw_text'):
                meta['raw_text'] = (edcs_r.get('clean_text_interpretive_word')
                                    or edcs_r.get('inscription'))

        persons = record.get('persons', [])
        for i, person in enumerate(persons):
            attestation_id = f"{record['id']}_{i}"
            # Defensive scrub: model sometimes returns literal "null" string instead of None
            def clean(v):
                if isinstance(v, str) and v.strip().lower() == 'null':
                    return None
                if isinstance(v, str):
                    v = v.replace('\n', ' ').replace('/', ' ').strip()
                return v or None
            praenomen = clean(person.get('praenomen'))
            nomen = clean(person.get('nomen'))
            cognomen = clean(person.get('cognomen'))
            fixed_praenomen, nomen, cognomen = fix_praenomen(praenomen, nomen, cognomen)
            if fixed_praenomen != praenomen:
                praenomen_fixes += 1
            praenomen = fixed_praenomen
            # Skip extractions where all name fields are null (too fragmentary)
            if not praenomen and not nomen and not cognomen:
                continue
            # Deterministic mop-up of oblique-case nomina the model left undeclined.
            new_nomen = fix_nomen_case(nomen)
            if new_nomen != nomen:
                nomen_fixes += 1
            nomen = new_nomen

            def clean_display(v):
                if not isinstance(v, str):
                    return v
                return v.replace('\n', ' ').replace('/', ' ').strip() or None
            raw_name = clean_display(person.get('raw_name'))
            classifier_input = {
                'praenomen': praenomen, 'nomen': nomen, 'cognomen': cognomen,
                'raw_name': raw_name or '',
            }
            row = {
                'attestation_id': attestation_id,
                'source_id': record['id'],
                'province': province_name,
                'praenomen': praenomen,
                'nomen': nomen,
                'cognomen': cognomen,
                'gender': clean(person.get('gender')),
                'status': clean(person.get('status')),
                'raw_name': raw_name,
                'fragmentary': person.get('fragmentary', False),
                'is_deity': is_deity(classifier_input),
                'is_imperial': is_imperial_person(classifier_input),
                'is_bare_epithet': is_bare_epithet(classifier_input),
                'is_place': is_place(classifier_input),
                **meta,
            }
            rows.append(row)

    df = pd.DataFrame(rows)
    
    # 3b. Sanitize for Parquet (Convert dicts/lists to strings)
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
            print(f"  Converting column '{col}' to string for Parquet compatibility...")
            df[col] = df[col].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
    
    # 4. Final Export
    print(f"Exporting {len(df)} name attestations to {output_parquet}...")
    # Using fastparquet or pyarrow for parquet export
    df.to_parquet(output_parquet, compression='snappy', index=False)
    df.to_csv(output_csv, index=False)
    
    print("\n" + "="*30)
    print("FINAL DELIVERABLE CREATED")
    print("="*30)
    print(f"Total Names Extracted: {len(df)}")
    print(f"  flagged is_deity:        {df['is_deity'].sum()}")
    print(f"  flagged is_imperial:     {df['is_imperial'].sum()}")
    print(f"  flagged is_bare_epithet: {df['is_bare_epithet'].sum()}")
    print(f"  flagged is_place:        {df['is_place'].sum()}")
    print(f"  flagged fragmentary:     {df['fragmentary'].sum()}")
    print(f"Praenomen reclassifications (off-whitelist → nomen): {praenomen_fixes}")
    print(f"Nomen nominalizations (oblique → nominative):        {nomen_fixes}")
    print(f"Parquet File: {output_parquet}")
    print(f"CSV File:     {output_csv}")
    print("="*30)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--province', default='africa_proconsularis',
                        help='Province slug matching the NER output filename prefix')
    parser.add_argument('--province-name', default=None,
                        help='Display name for province column (default: derived from slug)')
    args = parser.parse_args()
    pname = args.province_name or args.province.replace('_', ' ').title()
    create_final_dataset(province_slug=args.province, province_name=pname)
