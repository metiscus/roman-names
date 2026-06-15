"""
One-shot migration: backfill EDH metadata into the inscriptions table.

New columns added (skipped if already present):
  material        - stone/material type (e.g. "Marmor")
  dimensions      - "HxWxD cm" string, omitting blank values
  current_location - aufbewahrung (where the stone is held now)
  photos          - JSON array of {thumb, detail} objects for Heidicon images
  bibliography    - literatur field from EDH

Sources:
  edh_data_text.csv  - keyed by hd_nr; foto_nr gives F_NR|thumb_url pairs
  edh_data_foto.csv  - keyed by f_nr; heidicon_detail gives per-photo detail URL
"""
import csv
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).parent.parent
EDH_TEXT = REPO / "edh_data_text.csv"
DB_PATH = REPO / "roman_names.db"

NEW_COLS = [
    ("material", "TEXT"),
    ("dimensions", "TEXT"),
    ("current_location", "TEXT"),
    ("photos", "TEXT"),
    ("bibliography", "TEXT"),
]


def add_columns(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(inscriptions)")}
    for col, coltype in NEW_COLS:
        if col not in existing:
            db.execute(f"ALTER TABLE inscriptions ADD COLUMN {col} {coltype}")
            print(f"  Added column: {col}")
        else:
            print(f"  Column already exists: {col}")
    db.commit()


EDH_FOTO_BASE = "https://edh-www.adw.uni-heidelberg.de/edh/foto/"


def parse_photos(foto_nr: str) -> list[dict]:
    """Extract {thumb, detail} pairs from 'FXXXXXX|thumb_url FXXXXXX|thumb_url' string."""
    photos = []
    for part in foto_nr.split(" "):
        part = part.strip()
        if "|" not in part:
            continue
        fnr, thumb = part.split("|", 1)
        if not thumb:
            continue
        photos.append({"thumb": thumb, "detail": EDH_FOTO_BASE + fnr})
    return photos


def parse_dimensions(row: dict) -> str | None:
    parts = []
    for key in ("hoehe", "breite", "tiefe"):
        val = row.get(key, "").strip()
        if val:
            try:
                parts.append(str(int(float(val))))
            except ValueError:
                parts.append(val)
    if not parts:
        return None
    return "×".join(parts) + " cm"


def load_edh_text() -> dict:
    """Return hd_nr → metadata dict."""
    print(f"Loading {EDH_TEXT.name}...")
    lookup = {}
    with open(EDH_TEXT, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            hd = row["hd_nr"].strip()
            if not hd:
                continue
            photos = parse_photos(row.get("foto_nr", ""))
            lookup[hd] = {
                "material": row.get("material", "").strip() or None,
                "dimensions": parse_dimensions(row),
                "current_location": row.get("aufbewahrung", "").strip() or None,
                "photos": json.dumps(photos, ensure_ascii=False) if photos else None,
                "bibliography": row.get("literatur", "").strip() or None,
            }
    print(f"  {len(lookup)} EDH text records loaded")
    return lookup


def patch(db: sqlite3.Connection, lookup: dict) -> None:
    rows = db.execute(
        "SELECT edcs_id, edh_id FROM inscriptions WHERE edh_id IS NOT NULL AND edh_id != ''"
    ).fetchall()
    print(f"\nInscriptions with edh_id: {len(rows)}")

    updated = skipped = 0
    for edcs_id, edh_id in rows:
        meta = lookup.get(edh_id)
        if not meta:
            skipped += 1
            continue
        db.execute(
            """UPDATE inscriptions
               SET material = ?,
                   dimensions = ?,
                   current_location = ?,
                   photos = ?,
                   bibliography = ?
               WHERE edcs_id = ?""",
            (
                meta["material"],
                meta["dimensions"],
                meta["current_location"],
                meta["photos"],
                meta["bibliography"],
                edcs_id,
            ),
        )
        updated += 1

    db.commit()
    print(f"  Updated: {updated}")
    print(f"  No EDH text record found: {skipped}")

    # Quick coverage summary
    for col, _ in NEW_COLS:
        count = db.execute(
            f"SELECT COUNT(*) FROM inscriptions WHERE {col} IS NOT NULL"
        ).fetchone()[0]
        print(f"  {col}: {count} rows populated")


if __name__ == "__main__":
    db = sqlite3.connect(DB_PATH)
    print("Adding columns...")
    add_columns(db)
    lookup = load_edh_text()
    print("\nPatching inscriptions...")
    patch(db, lookup)
    print("\nDone.")
