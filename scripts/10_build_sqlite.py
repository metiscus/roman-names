#!/usr/bin/env python3
"""Load all per-province GeoJSON files into roman_names.db."""

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TILE_ZOOM      = 10  # base zoom level used to pre-index inscription tiles
AGGREGATE_ZOOM = 7   # precomputed grid zoom for intermediate view (5 ≤ zoom < 8)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "roman_names.db"
DEFAULT_GEOJSON_DIR = Path(__file__).parent.parent / "webapp" / "data"

# persons and overrides both store JSON text. Always serialize with json.dumps() on
# write and deserialize with json.loads() on read. The build script writes persons;
# overrides is written by admin/correction tooling.
_CREATE_INSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS inscriptions (
    edcs_id     TEXT PRIMARY KEY,
    province    TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    findspot    TEXT,
    raw_text    TEXT,
    date_from   INTEGER,
    date_to     INTEGER,
    persons     TEXT NOT NULL,
    overrides   TEXT,
    translation TEXT,
    summary     TEXT,
    tile_x      INTEGER NOT NULL DEFAULT 0,
    tile_y      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
)
"""

_CREATE_TILE_AGGREGATES = """
CREATE TABLE IF NOT EXISTS tile_aggregates (
    zoom   INTEGER NOT NULL,
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    lat    REAL NOT NULL,
    lon    REAL NOT NULL,
    count  INTEGER NOT NULL,
    PRIMARY KEY (zoom, tile_x, tile_y)
)
"""

_CREATE_PROVINCES = """
CREATE TABLE IF NOT EXISTS provinces (
    province TEXT PRIMARY KEY,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    count    INTEGER NOT NULL
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
    "CREATE INDEX IF NOT EXISTS idx_inscriptions_tile ON inscriptions (tile_x, tile_y)",
    "CREATE INDEX IF NOT EXISTS idx_inscriptions_province ON inscriptions (province)",
]

_UPSERT = """
INSERT INTO inscriptions
    (edcs_id, province, lat, lon, findspot, raw_text, date_from, date_to,
     persons, translation, summary, tile_x, tile_y, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(edcs_id) DO UPDATE SET
    province    = excluded.province,
    lat         = excluded.lat,
    lon         = excluded.lon,
    findspot    = excluded.findspot,
    raw_text    = excluded.raw_text,
    date_from   = excluded.date_from,
    date_to     = excluded.date_to,
    persons     = excluded.persons,
    translation = excluded.translation,
    summary     = excluded.summary,
    tile_x      = excluded.tile_x,
    tile_y      = excluded.tile_y,
    updated_at  = excluded.updated_at
    -- overrides intentionally omitted: manual corrections survive pipeline re-runs
"""


def lat_lon_to_tile(lat: float, lon: float, zoom: int = TILE_ZOOM) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _load_enrichment(geojson_dir: Path) -> dict[str, dict]:
    enrichment: dict[str, dict] = {}
    for path in geojson_dir.glob("enrichment_*.json"):
        with open(path) as f:
            enrichment.update(json.load(f))
    return enrichment


def _load_geojson(
    path: Path,
    province: str,
    conn: sqlite3.Connection,
    now: str,
    enrichment: dict[str, dict],
) -> tuple[int, int]:
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
        lat, lon = float(lat), float(lon)
        tile_x, tile_y = lat_lon_to_tile(lat, lon)
        enr = enrichment.get(edcs_id, {})
        rows.append((
            edcs_id,
            province,
            lat,
            lon,
            props.get("findspot"),
            props.get("raw_text"),
            props.get("date_from"),
            props.get("date_to"),
            json.dumps(props.get("persons", [])),
            enr.get("translation"),
            enr.get("summary"),
            tile_x,
            tile_y,
            now,
        ))

    conn.executemany(_UPSERT, rows)
    conn.commit()
    return len(rows), skipped


def _build_tile_aggregates(conn: sqlite3.Connection) -> int:
    divisor = 2 ** (TILE_ZOOM - AGGREGATE_ZOOM)
    conn.execute("DELETE FROM tile_aggregates")
    conn.execute(f"""
        INSERT INTO tile_aggregates (zoom, tile_x, tile_y, lat, lon, count)
        SELECT {AGGREGATE_ZOOM},
               tile_x / {divisor},
               tile_y / {divisor},
               AVG(lat),
               AVG(lon),
               COUNT(*)
        FROM inscriptions
        GROUP BY tile_x / {divisor}, tile_y / {divisor}
    """)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM tile_aggregates").fetchone()[0]


def _build_provinces(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM provinces")
    conn.execute("""
        INSERT INTO provinces (province, lat, lon, count)
        SELECT province, AVG(lat), AVG(lon), COUNT(*)
        FROM inscriptions
        GROUP BY province
    """)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM provinces").fetchone()[0]


def build(
    db_path: Path = DEFAULT_DB_PATH,
    geojson_dir: Path = DEFAULT_GEOJSON_DIR,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_INSCRIPTIONS)
        conn.execute(_CREATE_TILE_AGGREGATES)
        conn.execute(_CREATE_PROVINCES)
        conn.execute(_CREATE_FLAGS)
        for idx in _INDEXES:
            conn.execute(idx)
        conn.commit()

        geojson_files = sorted(geojson_dir.glob("inscriptions_*.geojson"))
        enrichment = _load_enrichment(geojson_dir)
        now = datetime.now(timezone.utc).isoformat()
        total_loaded = total_skipped = 0

        for path in geojson_files:
            province = path.stem.removeprefix("inscriptions_")
            loaded, skipped = _load_geojson(path, province, conn, now, enrichment)
            print(f"  {province}: {loaded} loaded, {skipped} skipped")
            total_loaded += loaded
            total_skipped += skipped

        n_provinces = _build_provinces(conn)
        n_aggregates = _build_tile_aggregates(conn)
        enriched = sum(
            1 for v in enrichment.values()
            if v.get("translation") or v.get("summary")
        )
        print(f"Enrichment: {enriched} records with translation/summary")
    finally:
        conn.close()

    print(f"\nTotal: {total_loaded} inscriptions, {total_skipped} skipped")
    print(f"Provinces: {n_provinces} (precomputed)")
    print(f"Tile aggregates: {n_aggregates} cells at zoom {AGGREGATE_ZOOM}")
    print(f"Database: {db_path}")


if __name__ == "__main__":
    build()
