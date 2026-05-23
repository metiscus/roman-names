import json
import pandas as pd
from tqdm import tqdm
import os

# Canonical Latin praenomina. Anything else in the praenomen field is a
# misclassification (most often a nomen like Flavius/Iulius the model anchored
# positionally) and gets rotated left at export time.
CANONICAL_PRAENOMINA = {
    # 18 standard male praenomina (Gaius/Caius and Kaeso/Caeso are spelling variants)
    'Lucius', 'Gaius', 'Caius', 'Marcus', 'Quintus', 'Publius', 'Titus',
    'Sextus', 'Tiberius', 'Aulus', 'Gnaeus', 'Decimus', 'Numerius',
    'Servius', 'Manius', 'Appius', 'Kaeso', 'Caeso', 'Spurius', 'Mamercus',
    # Feminine forms — Roman women occasionally bore praenomina
    'Gaia', 'Caia', 'Lucia', 'Marcia', 'Publia', 'Quinta', 'Sexta', 'Tita',
    'Tiberia', 'Aula', 'Decima', 'Numeria', 'Servia', 'Mania', 'Appia',
}


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


def create_final_dataset():
    # 1. Load the big NER results (JSONL format)
    input_ner_path = 'data/output/africa_proconsularis_ner_full.jsonl'
    output_parquet = 'data/roman_names_africa_proconsularis.parquet'
    output_csv = 'data/roman_names_africa_proconsularis.csv'

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
    lire_path = 'data/LIRE_v1-2.geojson'
    with open(lire_path, 'r', encoding='utf-8') as f:
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
    edcs_path = 'data/EDCS_text_cleaned_2022-09-12.json'
    with open(edcs_path, 'r', encoding='utf-8') as f:
        edcs_data = json.load(f)

    empty_meta = {'findspot': None, 'latitude': None, 'longitude': None,
                  'date_from': None, 'date_to': None, 'inscription_type': None, 'raw_text': None}
    edcs_lookup = {r['EDCS-ID']: r for r in edcs_data if r.get('EDCS-ID')}

    # 3. Flatten and Join
    print(f"Flattening {len(ner_results)} records into name attestations...")
    rows = []
    praenomen_fixes = 0
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
                return v
            praenomen = clean(person.get('praenomen'))
            nomen = clean(person.get('nomen'))
            cognomen = clean(person.get('cognomen'))
            fixed_praenomen, nomen, cognomen = fix_praenomen(praenomen, nomen, cognomen)
            if fixed_praenomen != praenomen:
                praenomen_fixes += 1
            praenomen = fixed_praenomen

            row = {
                'attestation_id': attestation_id,
                'source_id': record['id'],
                'province': 'Africa proconsularis',
                'praenomen': praenomen,
                'nomen': nomen,
                'cognomen': cognomen,
                'gender': clean(person.get('gender')),
                'status': clean(person.get('status')),
                'raw_name': person.get('raw_name'),
                'fragmentary': person.get('fragmentary', False),
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
    print(f"Praenomen reclassifications (off-whitelist → nomen): {praenomen_fixes}")
    print(f"Parquet File: {output_parquet}")
    print(f"CSV File:     {output_csv}")
    print("="*30)

if __name__ == "__main__":
    create_final_dataset()
