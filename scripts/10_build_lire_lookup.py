"""
Build a compact LIRE enrichment lookup keyed by EDCS-ID.

Reads data/LIRE_v1-2.geojson and writes data/lire_enrichment.json with
fields useful for enriching webapp popups: interpretive text, publication
reference, and external database links/photo URL.

Only fields with non-empty values are written per record to keep the output
file compact. Run once before (re)building province webapp data.
"""
import json
import re
import sys
from pathlib import Path


LIRE_PATH = Path("data/LIRE_v1-2.geojson")
OUTPUT_PATH = Path("data/lire_enrichment.json")


def derive_photo_url(photo_field: str) -> str:
    """
    Convert an old LIRE/EDCS photo field value to a CIL ACE image URL.

    Old format: http://db.edcs.eu/epigr/bilder.php?...&bild=PH0003385
    or:         http://db.edcs.eu/epigr/bilder.php?bilder.php?...&bild=$PH0003385
    New format: https://cil.bbaw.de/ace/resources/PH/{bucket}/{filename}.jpg

    Bucket is computed as 5000-entry ranges: PH0000001–PH0005000 → "0000001-0005000".
    """
    if not photo_field or not isinstance(photo_field, str):
        return ""
    # Extract PH-number (with or without leading $)
    m = re.search(r'\$?PH(\d+)', photo_field)
    if not m:
        return ""
    n = int(m.group(1))
    bucket_start = (n // 5000) * 5000 + 1
    bucket_end = (n // 5000 + 1) * 5000
    bucket = f"{bucket_start:07d}-{bucket_end:07d}"
    filename = f"PH{n:07d}"
    return f"https://cil.bbaw.de/ace/resources/PH/{bucket}/{filename}.jpg"


def extract_cil_ace_id(links_field: str) -> int | None:
    """
    Extract numeric CIL ACE id from the LIRE Links field.

    Links contains entries like:
      http://db.edcs.eu/epigr/partner.php?s_language=en&param=CO0008345;HD011889;...
    CO0008345 → 8345 → https://cil.bbaw.de/ace/id/8345
    """
    if not links_field or not isinstance(links_field, str):
        return None
    m = re.search(r'CO(\d+)', links_field)
    if not m:
        return None
    return int(m.group(1))


def clean_str(val) -> str:
    if not val or not isinstance(val, str) or val.strip() in ('', '{}', 'None'):
        return ""
    return val.strip()


def build_lire_lookup():
    print(f"Loading {LIRE_PATH} ...")
    with open(LIRE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"  {len(features):,} features")

    lookup: dict[str, dict] = {}
    skipped_no_id = 0

    for feat in features:
        props = feat.get("properties", {})
        edcs_id = clean_str(props.get("EDCS-ID", ""))
        if not edcs_id:
            skipped_no_id += 1
            continue

        record: dict = {}

        text = clean_str(props.get("text_edition", ""))
        if text:
            record["text_edition"] = text

        pub = clean_str(props.get("publication", ""))
        if pub:
            record["publication"] = pub

        cil_id = extract_cil_ace_id(props.get("Links", ""))
        if cil_id:
            record["cil_ace_id"] = cil_id

        edh_id = clean_str(props.get("EDH-ID", ""))
        if edh_id:
            record["edh_id"] = edh_id

        tm_uri = clean_str(props.get("trismegistos_uri", ""))
        if tm_uri:
            record["tm_uri"] = tm_uri

        photo_url = derive_photo_url(props.get("photo", ""))
        if photo_url:
            record["photo_url"] = photo_url

        ext_img = clean_str(props.get("external_image_uris", ""))
        if ext_img and "lupa.at" in ext_img:
            lupa_url = ext_img.replace("http://lupa.at/", "https://lupa.at/").replace("http://www.lupa.at/", "https://lupa.at/")
            record["lupa_url"] = lupa_url

        if record:
            lookup[edcs_id] = record

    print(f"  Enrichment records written: {len(lookup):,}")
    print(f"  Skipped (no EDCS-ID):       {skipped_no_id:,}")

    # Coverage stats
    for key in ("text_edition", "publication", "cil_ace_id", "edh_id", "tm_uri", "photo_url", "lupa_url"):
        n = sum(1 for r in lookup.values() if key in r)
        print(f"  {key:20s}: {n:,} ({n/len(lookup):.0%})")

    print(f"\nWriting {OUTPUT_PATH} ...")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(lookup, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = OUTPUT_PATH.stat().st_size / 1_000_000
    print(f"Done. Output size: {size_mb:.1f} MB")


if __name__ == "__main__":
    # Allow running from repo root or scripts/ directory
    import os
    if not LIRE_PATH.exists():
        alt = Path("../") / LIRE_PATH
        if alt.exists():
            os.chdir("..")
        else:
            print(f"ERROR: {LIRE_PATH} not found. Run from repo root.", file=sys.stderr)
            sys.exit(1)
    build_lire_lookup()
