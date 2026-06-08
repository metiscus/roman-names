"""
One-shot script to backfill date_from / date_to into all per-province dataset
files using LIRE v3.0 as the authoritative source.

Patches:
  data/roman_names_*.csv        (source_id = full EDCS-XXXXXXXX)
  webapp/data/inscriptions_*.geojson  (edcs_id = bare numeric string)
"""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).parent.parent
LIRE_PATH = REPO / "data" / "LIRE_v3-0.geojson"
CSV_DIR = REPO / "data"
GEOJSON_DIR = REPO / "webapp" / "data"


def to_int(v):
    if v is None:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def load_lire_dates() -> tuple[dict, dict]:
    """Return (full_id_map, bare_id_map) where values are (date_from, date_to)."""
    print("Loading LIRE dates...")
    with open(LIRE_PATH) as f:
        lire = json.load(f)

    full_map: dict[str, tuple] = {}
    bare_map: dict[str, tuple] = {}
    for feat in lire["features"]:
        props = feat["properties"]
        eid = props.get("EDCS-ID")
        if not eid:
            continue
        pair = (to_int(props.get("not_before")), to_int(props.get("not_after")))
        full_map[eid] = pair
        bare_map[eid.replace("EDCS-", "")] = pair

    print(f"  {len(full_map)} LIRE records with dates")
    return full_map, bare_map


def patch_csvs(full_map: dict) -> None:
    csvs = sorted(CSV_DIR.glob("roman_names_*.csv"))
    print(f"\nPatching {len(csvs)} CSV files...")
    total_patched = 0
    for path in csvs:
        df = pd.read_csv(path, dtype={"source_id": str})
        before = df["date_from"].notna().sum()

        dates = df["source_id"].map(lambda eid: full_map.get(eid, (None, None)))
        df["date_from"] = dates.map(lambda t: t[0])
        df["date_to"]   = dates.map(lambda t: t[1])

        after = df["date_from"].notna().sum()
        patched = after - before
        total_patched += patched
        df.to_csv(path, index=False)
        print(f"  {path.name}: {patched} dates filled ({after}/{len(df)} rows now have dates)")

    print(f"  Total rows patched: {total_patched}")


def patch_geojsons(full_map: dict) -> None:
    geojsons = sorted(GEOJSON_DIR.glob("inscriptions_*.geojson"))
    print(f"\nPatching {len(geojsons)} GeoJSON files...")
    total_patched = 0
    for path in geojsons:
        with open(path) as f:
            data = json.load(f)

        patched = 0
        for feat in data["features"]:
            props = feat["properties"]
            eid = str(props.get("edcs_id", ""))
            if eid in full_map:
                df_val, dt_val = full_map[eid]
                props["date_from"] = df_val
                props["date_to"]   = dt_val
                if df_val is not None or dt_val is not None:
                    patched += 1
            else:
                props["date_from"] = None
                props["date_to"]   = None

        total_patched += patched
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        print(f"  {path.name}: {patched}/{len(data['features'])} features have dates")

    print(f"  Total features with real dates: {total_patched}")


if __name__ == "__main__":
    full_map, bare_map = load_lire_dates()
    patch_csvs(full_map)
    patch_geojsons(full_map)
    print("\nDone.")
