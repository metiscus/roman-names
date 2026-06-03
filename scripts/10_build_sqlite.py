#!/usr/bin/env python3
"""Load all per-province GeoJSON files into roman_names.db."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent.parent / "roman_names.db"
DEFAULT_GEOJSON_DIR = Path(__file__).parent.parent / "webapp" / "data"

# persons and overrides both store JSON text. Always serialize with json.dumps() on
# write and deserialize with json.loads() on read. The build script writes persons;
# overrides is written by admin/correction tooling.
_CREATE_INSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS inscriptions (
    edcs_id    TEXT PRIMARY KEY,
    province   TEXT NOT NULL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    findspot   TEXT,
    raw_text   TEXT,
    date_from  INTEGER,
    date_to    INTEGER,
    persons    TEXT NOT NULL,
    overrides  TEXT,
    updated_at TEXT NOT NULL
)
"""

_CREATE_FLAGS = """
CREATE TABLE IF NOT EXISTS flags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    edcs_id    TEXT NOT NULL,
    category   TEXT NOT NULL,
    comment    TEXT,
    email      TEXT,
    created_at TEXT NOT NULL
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_inscriptions_lat_lon ON inscriptions (lat, lon)",
    "CREATE INDEX IF NOT EXISTS idx_inscriptions_province ON inscriptions (province)",
]

_UPSERT = """
INSERT INTO inscriptions
    (edcs_id, province, lat, lon, findspot, raw_text, date_from, date_to, persons, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(edcs_id) DO UPDATE SET
    province   = excluded.province,
    lat        = excluded.lat,
    lon        = excluded.lon,
    findspot   = excluded.findspot,
    raw_text   = excluded.raw_text,
    date_from  = excluded.date_from,
    date_to    = excluded.date_to,
    persons    = excluded.persons,
    updated_at = excluded.updated_at
"""


def _load_geojson(path: Path, province: str, conn: sqlite3.Connection, now: str) -> tuple[int, int]:
    with open(path) as f:
        data = json.load(f)

    rows = []
    skipped = 0

    for feature in data.get("features", []):
        geom = feature.get("geometry")
        props = feature.get("properties", {})

        if not geom or geom.get("type") != "Point":
            skipped += 1
            continue

        edcs_id = props.get("edcs_id")
        if not edcs_id:
            skipped += 1
            continue

        lon, lat = geom["coordinates"]
        rows.append((
            edcs_id,
            province,
            float(lat),
            float(lon),
            props.get("findspot"),
            props.get("raw_text"),
            props.get("date_from"),
            props.get("date_to"),
            json.dumps(props.get("persons", [])),
            now,
        ))

    conn.executemany(_UPSERT, rows)
    conn.commit()
    return len(rows), skipped


def build(
    db_path: Path = DEFAULT_DB_PATH,
    geojson_dir: Path = DEFAULT_GEOJSON_DIR,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_INSCRIPTIONS)
        conn.execute(_CREATE_FLAGS)
        for idx in _INDEXES:
            conn.execute(idx)
        conn.commit()

        geojson_files = sorted(geojson_dir.glob("inscriptions_*.geojson"))
        now = datetime.now(timezone.utc).isoformat()
        total_loaded = total_skipped = 0

        for path in geojson_files:
            province = path.stem.removeprefix("inscriptions_")
            loaded, skipped = _load_geojson(path, province, conn, now)
            print(f"  {province}: {loaded} loaded, {skipped} skipped")
            total_loaded += loaded
            total_skipped += skipped
    finally:
        conn.close()

    print(f"\nTotal: {total_loaded} inscriptions, {total_skipped} skipped")
    print(f"Provinces: {len(geojson_files)}")
    print(f"Database: {db_path}")


if __name__ == "__main__":
    build()
