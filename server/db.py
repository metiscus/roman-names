import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

ZOOM_PROVINCE   = 5   # below: province clusters
ZOOM_INDIVIDUAL = 8   # at/above: individual markers; between: grid aggregates
AGGREGATE_ZOOM  = 7   # precomputed aggregate zoom — must match 10_build_sqlite.py
TILE_ZOOM       = 10  # inscription tile zoom — must match 10_build_sqlite.py


def _parse_persons(overrides: str | None, persons: str) -> list:
    """Parse persons JSON, returning empty list on any JSON error."""
    try:
        if overrides:
            return json.loads(overrides)
        return json.loads(persons)
    except (json.JSONDecodeError, TypeError):
        return []


def _db_path() -> Path:
    return Path(os.environ.get(
        "ROMAN_NAMES_DB",
        str(Path(__file__).parent.parent / "roman_names.db"),
    ))


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def run_migrations() -> None:
    """Idempotent — call at every startup."""
    with _conn() as conn:
        for ddl in [
            "ALTER TABLE flags ADD COLUMN status TEXT NOT NULL DEFAULT 'open'",
            "ALTER TABLE flags ADD COLUMN resolved_at TEXT",
        ]:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                edcs_id    TEXT NOT NULL,
                field      TEXT NOT NULL,
                old_value  TEXT,
                new_value  TEXT,
                edited_at  TEXT NOT NULL,
                applied_at TEXT
            )
        """)
        conn.commit()


def _tile_range(z: int, x: int, y: int) -> tuple[int, int, int, int]:
    """Convert a tile at any zoom to a range of TILE_ZOOM tiles."""
    if z <= TILE_ZOOM:
        scale = 2 ** (TILE_ZOOM - z)
        return x * scale, (x + 1) * scale - 1, y * scale, (y + 1) * scale - 1
    else:
        scale = 2 ** (z - TILE_ZOOM)
        sx, sy = x // scale, y // scale
        return sx, sx, sy, sy


def _aggregate_tile_range(z: int, x: int, y: int) -> tuple[int, int, int, int]:
    """Convert a tile at zoom z to a range of AGGREGATE_ZOOM tiles."""
    if z <= AGGREGATE_ZOOM:
        scale = 2 ** (AGGREGATE_ZOOM - z)
        return x * scale, (x + 1) * scale - 1, y * scale, (y + 1) * scale - 1
    else:
        scale = 2 ** (z - AGGREGATE_ZOOM)
        ax, ay = x // scale, y // scale
        return ax, ax, ay, ay


def _matches_filters(
    persons: list,
    gender: str | None,
    confidence: str | None,
    hide_deity: bool,
    hide_imperial: bool,
    search: str | None
) -> bool:
    if search:
        search_lower = search.lower()
        hit = False
        for p in persons:
            full = " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen"), p.get("raw_name")])).lower()
            if search_lower in full:
                hit = True
                break
        if not hit:
            return False

    if gender or confidence or hide_deity or hide_imperial:
        relevant = []
        for p in persons:
            if hide_deity and p.get("is_deity"):
                continue
            if hide_imperial and p.get("is_imperial"):
                continue
            if gender and p.get("gender") != gender:
                continue
            if confidence and p.get("cluster_confidence") != confidence:
                continue
            relevant.append(p)
        if len(persons) > 0 and len(relevant) == 0:
            return False
    return True


def get_markers_for_tile(
    z: int, x: int, y: int,
    gender: str | None = None,
    confidence: str | None = None,
    hide_deity: bool = False,
    hide_imperial: bool = False,
    has_translation: bool = False,
    search: str | None = None
) -> dict:
    with _conn() as conn:
        if z < ZOOM_PROVINCE:
            rows = conn.execute("SELECT province, lat, lon, count FROM provinces").fetchall()
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

        elif z < ZOOM_INDIVIDUAL:
            ax_min, ax_max, ay_min, ay_max = _aggregate_tile_range(z, x, y)
            rows = conn.execute(
                """
                SELECT tile_x, tile_y, lat, lon, count
                FROM tile_aggregates
                WHERE zoom = ? AND tile_x BETWEEN ? AND ? AND tile_y BETWEEN ? AND ?
                """,
                (AGGREGATE_ZOOM, ax_min, ax_max, ay_min, ay_max),
            ).fetchall()
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "area_cluster",
                        "count": r["count"],
                        "tile_z": AGGREGATE_ZOOM,
                        "tile_x": r["tile_x"],
                        "tile_y": r["tile_y"],
                    },
                }
                for r in rows
            ]

        else:
            x_min, x_max, y_min, y_max = _tile_range(z, x, y)
            query = """
                SELECT edcs_id, lat, lon, findspot, date_from, date_to,
                       persons, overrides,
                       (translation IS NOT NULL AND translation != '') AS has_translation
                FROM inscriptions
                WHERE tile_x BETWEEN ? AND ? AND tile_y BETWEEN ? AND ?
            """
            params = [x_min, x_max, y_min, y_max]
            if has_translation:
                query += " AND (translation IS NOT NULL AND translation != '')"

            rows = conn.execute(query, params).fetchall()
            features = []
            for r in rows:
                parsed_persons = _parse_persons(r["overrides"], r["persons"])
                if not _matches_filters(
                    parsed_persons,
                    gender=gender,
                    confidence=confidence,
                    hide_deity=hide_deity,
                    hide_imperial=hide_imperial,
                    search=search
                ):
                    continue

                genders = list(set(p.get("gender") for p in parsed_persons if p.get("gender")))
                person_names = []
                for p in parsed_persons[:2]:
                    name = " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen")]))
                    display_name = name if name else (p.get("raw_name") or "(unnamed)")
                    person_names.append(display_name)

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "inscription",
                        "edcs_id": r["edcs_id"],
                        "findspot": r["findspot"],
                        "date_from": r["date_from"],
                        "date_to": r["date_to"],
                        "edcs_url": f"https://edcs.hist.uzh.ch/en/document?edcs-id={r['edcs_id']}",
                        "genders": genders,
                        "person_names": person_names,
                        "person_count": len(parsed_persons),
                        "has_translation": bool(r["has_translation"]),
                    },
                })

    return {"type": "FeatureCollection", "features": features}
def get_inscription(edcs_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute(
            """
            SELECT edcs_id, province, lat, lon, findspot, raw_text,
                   date_from, date_to, persons, overrides, translation, summary
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
        "edcs_url": f"https://edcs.hist.uzh.ch/en/document?edcs-id={r['edcs_id']}",
        "persons": _parse_persons(r["overrides"], r["persons"]),
        "has_overrides": r["overrides"] is not None,
        "translation": r["translation"],
        "summary": r["summary"],
    }


def get_flags(status: str | None = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM flags WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM flags ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def update_flag_status(flag_id: int, status: str) -> None:
    resolved_at = datetime.now(timezone.utc).isoformat() if status == "resolved" else None
    with _conn() as conn:
        conn.execute(
            "UPDATE flags SET status = ?, resolved_at = ? WHERE id = ?",
            (status, resolved_at, flag_id),
        )
        conn.commit()


def get_inscription_for_edit(edcs_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute(
            """SELECT edcs_id, findspot, raw_text, persons, overrides,
                      translation, summary
               FROM inscriptions WHERE edcs_id = ?""",
            (edcs_id,),
        ).fetchone()
    return dict(r) if r else None


_EDITABLE_FIELDS: dict[str, str] = {
    "persons": "overrides",
    "translation": "translation",
    "summary": "summary",
}


def save_edit(edcs_id: str, field: str, new_value: str | None) -> None:
    col = _EDITABLE_FIELDS.get(field)
    if col is None:
        raise ValueError(f"Unknown field: {field!r}")
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT {col} FROM inscriptions WHERE edcs_id = ?", (edcs_id,)
        ).fetchone()
        old_value = row[col] if row else None
        conn.execute(
            f"UPDATE inscriptions SET {col} = ?, updated_at = ? WHERE edcs_id = ?",
            (new_value, now, edcs_id),
        )
        conn.execute(
            """INSERT INTO edit_log (edcs_id, field, old_value, new_value, edited_at)
               VALUES (?, ?, ?, ?, ?)""",
            (edcs_id, field, old_value, new_value, now),
        )
        conn.commit()


def get_edit_log(unapplied_only: bool = False) -> list[dict]:
    with _conn() as conn:
        if unapplied_only:
            rows = conn.execute(
                "SELECT * FROM edit_log WHERE applied_at IS NULL ORDER BY edited_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM edit_log ORDER BY edited_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def mark_edit_applied(edit_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE edit_log SET applied_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), edit_id),
        )
        conn.commit()


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
