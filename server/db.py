import csv
import io
import json
import os
import re
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
            "ALTER TABLE inscriptions ADD COLUMN edh_id TEXT",
            "ALTER TABLE inscriptions ADD COLUMN tm_uri TEXT",
            "ALTER TABLE inscriptions ADD COLUMN text_edition TEXT",
            "ALTER TABLE inscriptions ADD COLUMN inscription_type TEXT",
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

        # Backfill edh_id / tm_uri from enrichment JSONs if not yet populated
        populated = conn.execute(
            "SELECT 1 FROM inscriptions WHERE edh_id IS NOT NULL LIMIT 1"
        ).fetchone()
        if not populated:
            enrich_dir = Path(__file__).parent.parent / "webapp" / "data"
            for f in sorted(enrich_dir.glob("enrichment_*.json")):
                with open(f) as fh:
                    data = json.load(fh)
                for edcs_id, fields in data.items():
                    edh_id = fields.get("edh_id")
                    tm_uri = fields.get("tm_uri")
                    if edh_id or tm_uri:
                        conn.execute(
                            "UPDATE inscriptions SET edh_id=?, tm_uri=? WHERE edcs_id=?",
                            (edh_id, tm_uri, edcs_id),
                        )

        conn.commit()

    # FTS5 virtual table — standalone (not content-linked) for reliability.
    # Populated once on first run; data is static enough that a full rebuild
    # is only needed if the table is dropped or the db is rebuilt.
    with _conn() as conn:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS inscriptions_fts
            USING fts5(edcs_id UNINDEXED, raw_text)
        """)
        conn.commit()
        fts_empty = conn.execute(
            "SELECT COUNT(*) FROM inscriptions_fts"
        ).fetchone()[0] == 0
        if fts_empty:
            conn.execute("""
                INSERT INTO inscriptions_fts(edcs_id, raw_text)
                SELECT edcs_id, raw_text FROM inscriptions
                WHERE raw_text IS NOT NULL AND raw_text != ''
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
    search: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    exclude_undated: bool = False,
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
            if date_from is not None:
                query += " AND (date_to IS NULL OR date_to >= ?)"
                params.append(date_from)
            if date_to is not None:
                query += " AND (date_from IS NULL OR date_from <= ?)"
                params.append(date_to)
            if exclude_undated:
                query += " AND date_from IS NOT NULL AND date_to IS NOT NULL"

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
                   date_from, date_to, persons, overrides, translation, summary,
                   edh_id, tm_uri, text_edition, inscription_type
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
        "lat": r["lat"],
        "lon": r["lon"],
        "edh_id": r["edh_id"],
        "tm_uri": r["tm_uri"],
        "text_edition": r["text_edition"],
        "inscription_type": r["inscription_type"],
    }


def get_cluster_inscriptions(cluster_id: int, province: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT i.edcs_id, i.lat, i.lon, i.findspot, i.date_from, i.date_to,
                   COALESCE(i.overrides, i.persons) AS persons_json,
                   (i.translation IS NOT NULL AND i.translation != '') AS has_translation
            FROM inscriptions i, json_each(COALESCE(i.overrides, i.persons)) p
            WHERE json_extract(p.value, '$.cluster_id') = ?
              AND i.province = ?
            ORDER BY i.date_from
            """,
            (cluster_id, province),
        ).fetchall()
    result = []
    for r in rows:
        parsed = _parse_persons(None, r["persons_json"])
        names = []
        for p in parsed[:2]:
            name = " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen")]))
            names.append(name if name else (p.get("raw_name") or "(unnamed)"))
        result.append({
            "edcs_id": r["edcs_id"],
            "lat": r["lat"],
            "lon": r["lon"],
            "findspot": r["findspot"],
            "date_from": r["date_from"],
            "date_to": r["date_to"],
            "person_count": len(parsed),
            "person_names": names,
            "has_translation": bool(r["has_translation"]),
        })
    return result


def get_global_cluster_inscriptions(global_cluster_id: int) -> list[dict]:
    """Return all inscriptions whose persons contain the given global_cluster_id."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT i.edcs_id, i.province, i.lat, i.lon, i.findspot,
                   i.date_from, i.date_to,
                   COALESCE(i.overrides, i.persons) AS persons_json,
                   (i.translation IS NOT NULL AND i.translation != '') AS has_translation
            FROM inscriptions i, json_each(COALESCE(i.overrides, i.persons)) p
            WHERE json_extract(p.value, '$.global_cluster_id') = ?
            ORDER BY i.province, i.date_from
            """,
            (global_cluster_id,),
        ).fetchall()
    result = []
    for r in rows:
        parsed = _parse_persons(None, r["persons_json"])
        names = []
        for p in parsed[:2]:
            name = " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen")]))
            names.append(name if name else (p.get("raw_name") or "(unnamed)"))
        result.append({
            "edcs_id": r["edcs_id"],
            "province": r["province"],
            "lat": r["lat"],
            "lon": r["lon"],
            "findspot": r["findspot"],
            "date_from": r["date_from"],
            "date_to": r["date_to"],
            "person_count": len(parsed),
            "person_names": names,
            "has_translation": bool(r["has_translation"]),
        })
    return result


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


def get_provinces() -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT province FROM provinces ORDER BY province"
        ).fetchall()
    return [r["province"] for r in rows]


def _fts_query(q: str) -> str:
    """Convert a plain-text user query to an FTS5 prefix-match expression."""
    clean = re.sub(r'[^\w\s]', ' ', q, flags=re.UNICODE)
    terms = clean.strip().split()
    if not terms:
        return '""'
    return " ".join(f"{t}*" for t in terms)


def search_inscriptions(
    nomen: str | None = None,
    cognomen: str | None = None,
    praenomen: str | None = None,
    q: str | None = None,
    province: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    gender: str | None = None,
    inscription_type: str | None = None,
    page: int = 1,
    limit: int = 50,
    view: str = "inscriptions",
) -> tuple[int, list[dict]]:
    use_fts = q is not None and q.strip()
    use_persons = any([nomen, cognomen, praenomen, gender])

    select_cols = """
        SELECT DISTINCT i.edcs_id, i.province, i.lat, i.lon, i.findspot,
               i.date_from, i.date_to, i.inscription_type,
               COALESCE(i.overrides, i.persons) AS persons_json,
               i.translation, i.summary, i.edh_id, i.tm_uri,
               (i.translation IS NOT NULL AND i.translation != '') AS has_translation
    """
    from_clause = "FROM inscriptions i"
    if use_fts:
        from_clause += "\nJOIN inscriptions_fts fts ON fts.edcs_id = i.edcs_id"
    if use_persons:
        from_clause += "\n, json_each(COALESCE(i.overrides, i.persons)) p"

    where_parts: list[str] = []
    params: list = []

    if use_fts:
        where_parts.append("fts.raw_text MATCH ?")
        params.append(_fts_query(q))
    if nomen:
        where_parts.append("json_extract(p.value, '$.nomen') LIKE ?")
        params.append(f"%{nomen}%")
    if cognomen:
        where_parts.append("json_extract(p.value, '$.cognomen') LIKE ?")
        params.append(f"%{cognomen}%")
    if praenomen:
        where_parts.append("json_extract(p.value, '$.praenomen') LIKE ?")
        params.append(f"%{praenomen}%")
    if gender:
        where_parts.append("json_extract(p.value, '$.gender') = ?")
        params.append(gender)
    if province:
        where_parts.append("i.province = ?")
        params.append(province)
    if date_from is not None:
        where_parts.append("(i.date_to IS NULL OR i.date_to >= ?)")
        params.append(date_from)
    if date_to is not None:
        where_parts.append("(i.date_from IS NULL OR i.date_from <= ?)")
        params.append(date_to)
    if inscription_type:
        where_parts.append("i.inscription_type = ?")
        params.append(inscription_type)

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    count_sql = f"SELECT COUNT(DISTINCT i.edcs_id) {from_clause} {where_sql}"
    data_sql = (
        f"{select_cols} {from_clause} {where_sql}"
        " ORDER BY i.province, i.edcs_id LIMIT ? OFFSET ?"
    )
    offset = (page - 1) * limit

    with _conn() as conn:
        total = conn.execute(count_sql, params).fetchone()[0]
        rows = conn.execute(data_sql, params + [limit, offset]).fetchall()

    if view == "persons":
        results = []
        for r in rows:
            persons = _parse_persons(None, r["persons_json"])
            for p in persons:
                if gender and p.get("gender") != gender:
                    continue
                if nomen and nomen.lower() not in (p.get("nomen") or "").lower():
                    continue
                if cognomen and cognomen.lower() not in (p.get("cognomen") or "").lower():
                    continue
                if praenomen and praenomen.lower() not in (p.get("praenomen") or "").lower():
                    continue
                results.append({
                    "praenomen": p.get("praenomen"),
                    "nomen": p.get("nomen"),
                    "cognomen": p.get("cognomen"),
                    "raw_name": p.get("raw_name"),
                    "gender": p.get("gender"),
                    "is_deity": p.get("is_deity", False),
                    "is_imperial": p.get("is_imperial", False),
                    "edcs_id": r["edcs_id"],
                    "province": r["province"],
                    "date_from": r["date_from"],
                    "date_to": r["date_to"],
                })
        return total, results

    results = []
    for r in rows:
        persons = _parse_persons(None, r["persons_json"])
        results.append({
            "edcs_id": r["edcs_id"],
            "province": r["province"],
            "findspot": r["findspot"],
            "date_from": r["date_from"],
            "date_to": r["date_to"],
            "inscription_type": r["inscription_type"],
            "persons": persons,
            "has_translation": bool(r["has_translation"]),
            "translation": r["translation"],
            "summary": r["summary"],
            "edh_id": r["edh_id"],
            "tm_uri": r["tm_uri"],
        })
    return total, results


def get_name_stats(
    nomen: str | None = None,
    province: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
) -> dict:
    where_parts: list[str] = []
    params: list = []

    if nomen:
        where_parts.append("json_extract(p.value, '$.nomen') LIKE ?")
        params.append(f"%{nomen}%")
    if province:
        where_parts.append("i.province = ?")
        params.append(province)
    if date_from is not None:
        where_parts.append("(i.date_to IS NULL OR i.date_to >= ?)")
        params.append(date_from)
    if date_to is not None:
        where_parts.append("(i.date_from IS NULL OR i.date_from <= ?)")
        params.append(date_to)

    base = "FROM inscriptions i, json_each(COALESCE(i.overrides, i.persons)) p"
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    with _conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) {base} {where_sql}", params
        ).fetchone()[0]

        by_nomen = conn.execute(
            f"SELECT json_extract(p.value, '$.nomen') n, COUNT(*) c"
            f" {base} {where_sql} GROUP BY n ORDER BY c DESC LIMIT 50",
            params,
        ).fetchall()

        by_cognomen = conn.execute(
            f"SELECT json_extract(p.value, '$.cognomen') n, COUNT(*) c"
            f" {base} {where_sql} GROUP BY n ORDER BY c DESC LIMIT 50",
            params,
        ).fetchall()

        by_province = conn.execute(
            f"SELECT i.province, COUNT(*) c"
            f" {base} {where_sql} GROUP BY i.province ORDER BY c DESC",
            params,
        ).fetchall()

        by_gender = conn.execute(
            f"SELECT json_extract(p.value, '$.gender') g, COUNT(*) c"
            f" {base} {where_sql} GROUP BY g",
            params,
        ).fetchall()

    return {
        "total_persons": total,
        "by_nomen": [{"name": r[0], "count": r[1]} for r in by_nomen if r[0]],
        "by_cognomen": [{"name": r[0], "count": r[1]} for r in by_cognomen if r[0]],
        "by_province": [{"province": r[0], "count": r[1]} for r in by_province if r[0]],
        "by_gender": {r[0]: r[1] for r in by_gender if r[0]},
    }


_ATTRIBUTION_HEADER = (
    "# Roman Names — machine-generated personal-name attestations from Latin inscriptions\n"
    "# Michael A Bosse, derived from EDCS 2022 (doi:10.5281/zenodo.7072337)"
    " and LIRE v3.0 (doi:10.5281/zenodo.8431452)\n"
    "# License: CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/\n"
    "# Attribution required. Translations, name extraction, and clusters are"
    " machine-generated and require verification.\n"
)


def results_to_csv(results: list[dict], view: str) -> str:
    buf = io.StringIO()
    buf.write(_ATTRIBUTION_HEADER)

    if view == "persons":
        fieldnames = [
            "praenomen", "nomen", "cognomen", "raw_name", "gender",
            "is_deity", "is_imperial", "edcs_id", "province", "date_from", "date_to",
        ]
    else:
        fieldnames = [
            "edcs_id", "province", "findspot", "date_from", "date_to",
            "inscription_type", "persons_count", "persons_names",
            "has_translation", "edh_id", "tm_uri",
        ]

    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for row in results:
        if view != "persons":
            persons = row.get("persons", [])
            names = "; ".join(
                " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen")]))
                or p.get("raw_name", "(unnamed)")
                for p in persons
            )
            row = {**row, "persons_count": len(persons), "persons_names": names}
        writer.writerow(row)

    return buf.getvalue()
