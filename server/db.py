import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

ZOOM_CLUSTER_THRESHOLD = 6


def _db_path() -> Path:
    return Path(os.environ.get(
        "ROMAN_NAMES_DB",
        str(Path(__file__).parent.parent / "roman_names.db"),
    ))


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def get_markers_in_bbox(
    west: float, south: float, east: float, north: float, zoom: int
) -> dict:
    with _conn() as conn:
        if zoom < ZOOM_CLUSTER_THRESHOLD:
            rows = conn.execute(
                """
                SELECT province, AVG(lat) AS lat, AVG(lon) AS lon, COUNT(*) AS count
                FROM inscriptions
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                GROUP BY province
                """,
                (south, north, west, east),
            ).fetchall()
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "province_cluster",
                        "province": r["province"],
                        "count": r["count"],
                    },
                }
                for r in rows
            ]
        else:
            rows = conn.execute(
                """
                SELECT edcs_id, lat, lon, findspot, date_from, date_to,
                       persons, overrides
                FROM inscriptions
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                """,
                (south, north, west, east),
            ).fetchall()
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "inscription",
                        "edcs_id": r["edcs_id"],
                        "findspot": r["findspot"],
                        "date_from": r["date_from"],
                        "date_to": r["date_to"],
                        "edcs_url": f"https://db.edcs.eu/epigr/epi_single.php?p_edcs_id={r['edcs_id']}",
                        "persons": json.loads(r["overrides"]) if r["overrides"] else json.loads(r["persons"]),
                        "has_overrides": r["overrides"] is not None,
                    },
                }
                for r in rows
            ]
    return {"type": "FeatureCollection", "features": features}


def get_inscription(edcs_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute(
            """
            SELECT edcs_id, province, lat, lon, findspot, raw_text,
                   date_from, date_to, persons, overrides
            FROM inscriptions WHERE edcs_id = ?
            """,
            (edcs_id,),
        ).fetchone()
    if r is None:
        return None
    return {
        "edcs_id": r["edcs_id"],
        "province": r["province"],
        "findspot": r["findspot"],
        "raw_text": r["raw_text"],
        "date_from": r["date_from"],
        "date_to": r["date_to"],
        "edcs_url": f"https://db.edcs.eu/epigr/epi_single.php?p_edcs_id={r['edcs_id']}",
        "persons": json.loads(r["overrides"]) if r["overrides"] else json.loads(r["persons"]),
        "has_overrides": r["overrides"] is not None,
    }


def insert_flag(
    edcs_id: str,
    category: str,
    comment: str | None,
    email: str | None,
) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO flags (edcs_id, category, comment, email, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (edcs_id, category, comment, email, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
