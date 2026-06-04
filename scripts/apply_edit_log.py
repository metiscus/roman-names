"""
Apply unapplied edit_log entries to webapp dataset files.

Usage:
  python scripts/apply_edit_log.py [--db PATH] [--dry-run]

Patches:
  webapp/data/enrichment_*.json      for translation / summary edits
  webapp/data/inscriptions_*.geojson for persons edits

Does NOT touch roman_names_*.csv — persons edits require re-running clustering.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent.parent
WEBAPP_DATA = REPO / "webapp" / "data"
DEFAULT_DB = REPO / "roman_names.db"


def get_province(conn: sqlite3.Connection, edcs_id: str) -> str | None:
    row = conn.execute(
        "SELECT province FROM inscriptions WHERE edcs_id = ?", (edcs_id,)
    ).fetchone()
    return row[0] if row else None


def patch_enrichment(province: str, edcs_id: str, field: str, new_value: str | None) -> bool:
    path = WEBAPP_DATA / f"enrichment_{province}.json"
    if not path.exists():
        print(f"  SKIP enrichment file not found: {path.name}")
        return False
    with open(path) as f:
        data = json.load(f)
    if edcs_id not in data:
        data[edcs_id] = {}
    data[edcs_id][field] = new_value
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    return True


def patch_geojson_persons(province: str, edcs_id: str, new_value: str | None) -> bool:
    path = WEBAPP_DATA / f"inscriptions_{province}.geojson"
    if not path.exists():
        print(f"  SKIP geojson file not found: {path.name}")
        return False
    with open(path) as f:
        data = json.load(f)
    patched = False
    for feat in data["features"]:
        if feat["properties"].get("edcs_id") == edcs_id:
            try:
                feat["properties"]["persons"] = json.loads(new_value) if new_value else []
            except json.JSONDecodeError:
                print(f"  WARN invalid JSON for persons on {edcs_id}, skipping")
                return False
            patched = True
            break
    if not patched:
        print(f"  WARN {edcs_id} not found in {path.name}")
        return False
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply edit_log entries to webapp data files")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to roman_names.db")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing files")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM edit_log WHERE applied_at IS NULL ORDER BY edited_at"
    ).fetchall()

    if not rows:
        print("No unapplied edits found.")
        conn.close()
        return

    print(f"Found {len(rows)} unapplied edit(s).")
    applied = 0

    for row in rows:
        edcs_id = row["edcs_id"]
        field = row["field"]
        new_value = row["new_value"]
        print(f"  [{row['id']}] {edcs_id} / {field}")

        province = get_province(conn, edcs_id)
        if not province:
            print(f"    SKIP inscription not found in DB")
            continue

        if args.dry_run:
            print(f"    DRY RUN: would patch {field} in {province}")
            continue

        ok = False
        if field in ("translation", "summary"):
            ok = patch_enrichment(province, edcs_id, field, new_value)
        elif field == "persons":
            ok = patch_geojson_persons(province, edcs_id, new_value)
        else:
            print(f"    SKIP unknown field: {field}")
            continue

        if ok:
            conn.execute(
                "UPDATE edit_log SET applied_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            conn.commit()
            applied += 1
            print(f"    OK patched {province}")

    conn.close()
    print(f"\nDone. {applied}/{len(rows)} edits applied.")
    if args.dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
