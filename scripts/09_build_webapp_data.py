import pandas as pd
import json
import os
import random
import re
import sys
from pathlib import Path

# Ensure name_filters can be imported when running from any directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import name_filters

# Paths resolved at runtime from --province arg (see __main__)

def safe_int(val, default=0):
    if pd.isna(val) or val == '':
        return default
    try:
        # If it's a string like "400; 201", take the first part
        if isinstance(val, str):
            val = val.split(';')[0].strip()
        return int(float(val))
    except (ValueError, TypeError):
        return default

def clean_name_component(val):
    """Strip epigraphic noise like [3] or [---] from display names."""
    if not isinstance(val, str) or not val:
        return ''
    # Remove anything inside brackets, including the brackets
    return re.sub(r'\[.*?\]', '', val).strip()

def get_marker_gender(genders):
    unique_genders = set(genders)
    has_male = 'male' in unique_genders
    has_female = 'female' in unique_genders
    
    if has_male and has_female:
        return 'mixed'
    if has_male:
        return 'male'
    if has_female:
        return 'female'
    return 'unknown'

def build_webapp_data(province='africa_proconsularis'):
    DATA_PATH = Path(f"data/roman_names_{province}.parquet")
    WEBAPP_DATA_DIR = Path("webapp/data")
    GEOJSON_OUTPUT = WEBAPP_DATA_DIR / f"inscriptions_{province}.geojson"
    CLUSTERS_OUTPUT = WEBAPP_DATA_DIR / f"clusters_{province}.json"

    print(f"Loading {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    
    # 1. Build findspot -> (lat, lon) lookup
    coords_df = df.dropna(subset=['latitude', 'longitude'])
    findspot_lookup = coords_df.groupby('findspot')[['latitude', 'longitude']].first().to_dict('index')
    print(f"Built lookup for {len(findspot_lookup)} unique findspots with coordinates.")

    # 2. Assign coordinates to rows missing them
    def get_coords(row):
        if not pd.isna(row['latitude']) and not pd.isna(row['longitude']):
            return row['latitude'], row['longitude']
        if row['findspot'] in findspot_lookup:
            res = findspot_lookup[row['findspot']]
            return res['latitude'], res['longitude']
        return None, None

    print("Resolving coordinates via findspot lookup...")
    coords_series = df.apply(get_coords, axis=1)
    df['latitude'] = coords_series.apply(lambda x: x[0])
    df['longitude'] = coords_series.apply(lambda x: x[1])

    # 3. Aggregate by source_id
    print("Aggregating attestations by source_id...")
    
    df = df.fillna({
        'praenomen': '', 'nomen': '', 'cognomen': '', 
        'gender': 'unknown', 'status': '',
        'raw_text': '', 'raw_name': '', 'findspot': 'Unknown'
    })

    # Count coordinate occurrences to identify stacks
    df['coord_key'] = df.apply(lambda r: (round(r['latitude'], 6), round(r['longitude'], 6)) if not pd.isna(r['latitude']) else None, axis=1)
    coord_counts = df.dropna(subset=['coord_key']).groupby('coord_key').size().to_dict()

    grouped = df.groupby('source_id')
    
    features = []
    skipped_count = 0
    mappable_count = 0
    clusters_map = {}

    for source_id, group in grouped:
        first_row = group.iloc[0]
        lat, lon = first_row['latitude'], first_row['longitude']
        
        geometry = None
        is_individual = True
        if not pd.isna(lat) and not pd.isna(lon):
            mappable_count += 1
            geometry = {
                "type": "Point",
                "coordinates": [float(lon), float(lat)]
            }
            # Determine if this is an "individually placed" find
            key = (round(lat, 6), round(lon, 6))
            if coord_counts.get(key, 0) > len(group):
                is_individual = False
        else:
            skipped_count += 1
        
        persons = []
        genders = []
        for _, row in group.iterrows():
            # Build basic person object with cleaned components
            person = {
                "praenomen": clean_name_component(row['praenomen']),
                "nomen": clean_name_component(row['nomen']),
                "cognomen": clean_name_component(row['cognomen']),
                "gender": row['gender'],
                "status": row['status'],
                "raw_name": row['raw_name'],
                "fragmentary": bool(row['fragmentary']),
                "cluster_id": int(row['cluster_id']) if not pd.isna(row['cluster_id']) else None,
                "cluster_size": int(row['cluster_size']) if not pd.isna(row['cluster_size']) else 0,
                "cluster_confidence": row['cluster_confidence']
            }
            
            # Dynamically re-apply non-person classifiers
            fp_type = name_filters.classify_non_person_fp(person)
            person["is_imperial"] = (fp_type == "imperial")
            person["is_deity"] = (fp_type == "deity")
            
            persons.append(person)
            genders.append(row['gender'])
            
            # Update clusters map
            cid = person['cluster_id']
            if cid is not None:
                if cid not in clusters_map:
                    clusters_map[cid] = set()
                clusters_map[cid].add(source_id)

        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "edcs_id": source_id,
                "findspot": first_row['findspot'],
                "raw_text": first_row['raw_text'],
                "date_from": safe_int(first_row['date_from']),
                "date_to": safe_int(first_row['date_to']),
                "marker_gender": get_marker_gender(genders),
                "is_individual": is_individual,
                "edcs_url": f"https://edcs.hist.uzh.ch/en/document?edcs-id={source_id}",
                "persons": persons
            }
        }
        features.append(feature)

    clusters_json = {str(k): list(v) for k, v in clusters_map.items()}

    WEBAPP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Writing {len(features)} features to {GEOJSON_OUTPUT}...")
    geojson = {"type": "FeatureCollection", "features": features}
    with open(GEOJSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"Writing cluster lookup to {CLUSTERS_OUTPUT}...")
    with open(CLUSTERS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(clusters_json, f, ensure_ascii=False)

    print("\nStats:")
    print(f"Total inscriptions: {len(grouped)}")
    print(f"Mappable inscriptions: {mappable_count} ({mappable_count/len(grouped):.1%})")
    print(f"Unique clusters: {len(clusters_json)}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--province', default='africa_proconsularis',
                        help='Province slug matching the parquet filename prefix')
    args = parser.parse_args()
    build_webapp_data(province=args.province)
