"""
Build an EDH (Heidelberg) ground truth dataset by mapping HD-IDs to EDCS-IDs via LIRE.

Reads:
    - data/edh_data_pers.csv (Bulk prosopography dump)
    - data/LIRE_v3-0.geojson (For HD -> EDCS mapping)

Outputs:
    - data/edh_gt.json (Same format as r1b1_gt.json)
"""

import json
import pandas as pd
import os

LIRE_PATH = "data/LIRE_v3-0.geojson"
EDH_CSV_PATH = "data/edh_data_pers.csv"
OUT_PATH = "data/edh_gt.json"

def main():
    print("Building HD-ID -> EDCS-ID map from LIRE...")
    with open(LIRE_PATH) as f:
        lire = json.load(f)
    
    hd_to_edcs = {}
    for feat in lire['features']:
        p = feat['properties']
        hd = p.get('EDH-ID')
        edcs = p.get('EDCS-ID')
        if hd and edcs:
            hd_to_edcs[hd] = edcs
    print(f"  Mapped {len(hd_to_edcs):,} HD-IDs to EDCS-IDs")

    print("\nReading EDH Prosopography CSV...")
    df = pd.read_csv(EDH_CSV_PATH)
    
    # Filter to only records we can map to EDCS
    df = df[df['hd_nr'].isin(hd_to_edcs.keys())]
    print(f"  Found {len(df):,} person records matching our LIRE corpus")

    gt = {}
    for hd_id, group in df.groupby('hd_nr'):
        edcs_id = hd_to_edcs[hd_id]
        persons = []
        for _, row in group.iterrows():
            # Clean names: "00" or empty means null
            def clean(val):
                if pd.isna(val) or str(val) == "00":
                    return None
                return str(val).replace('+', '').strip() # Remove the '+' reconstruction markers

            persons.append({
                "praenomen": clean(row['praenomen']),
                "nomen":     clean(row['nomen']),
                "cognomen":  clean(row['cognomen']),
                "gender":    "male" if row['geschlecht'] == "M" else "female" if row['geschlecht'] == "W" else "unknown"
            })
        gt[edcs_id] = persons

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)
    
    print(f"\nWrote {OUT_PATH} ({len(gt):,} inscriptions, {len(df):,} person records)")

if __name__ == "__main__":
    main()
