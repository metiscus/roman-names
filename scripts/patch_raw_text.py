"""Patch raw_text in the SQLite DB and geojson files.

The pipeline (06_export_to_dataset.py) used EDCS clean_text_interpretive_word
(fully expanded, line-breaks stripped) as raw_text for non-LIRE inscriptions
instead of the original inscription field, which preserves epigraphic notation
(/ line breaks, f(ilio) abbreviations, lacunae markers).

This script replaces raw_text with the EDCS inscription field wherever:
  - The EDCS source has a non-empty inscription value for that ID
  - That value differs from what is currently stored

Runs in dry-run mode by default. Pass --apply to make changes.
"""
import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

EDCS_PATH   = Path('data/EDCS_text_cleaned_2022-09-12.json')
DB_PATH     = Path('roman_names.db')
GEOJSON_DIR = Path('webapp/data')


def load_edcs_lookup() -> dict[str, str]:
    """Return {EDCS-ID: inscription_text} for records with non-empty inscription."""
    print(f'Loading {EDCS_PATH} ...')
    with open(EDCS_PATH) as f:
        data = json.load(f)
    lookup = {}
    for r in data:
        eid = r.get('EDCS-ID')
        text = r.get('inscription') or ''
        if eid and text:
            lookup[eid] = text
    print(f'  {len(lookup):,} EDCS records with inscription text')
    return lookup


def build_patch_map(edcs: dict[str, str], db_path: Path) -> dict[str, str]:
    """
    Compare EDCS inscription text against stored raw_text for every DB row.
    Returns {edcs_id: new_raw_text} for rows that need updating.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT edcs_id, raw_text FROM inscriptions').fetchall()
    conn.close()

    patch = {}
    for row in rows:
        eid = row['edcs_id']
        correct = edcs.get(eid)
        if correct and correct != row['raw_text']:
            patch[eid] = correct
    return patch


def patch_db(patch: dict[str, str], db_path: Path, dry_run: bool) -> None:
    """Apply raw_text corrections to the SQLite DB inside a single transaction."""
    print(f'\nDB: {len(patch):,} rows to update')
    if dry_run:
        print('  (dry run — no changes made)')
        return

    conn = sqlite3.connect(db_path)
    try:
        conn.execute('BEGIN')
        conn.executemany(
            'UPDATE inscriptions SET raw_text = ? WHERE edcs_id = ?',
            ((text, eid) for eid, text in patch.items()),
        )
        updated = conn.execute('SELECT total_changes()').fetchone()[0]
        conn.execute('COMMIT')
        print(f'  DB committed — {updated:,} rows updated')
    except Exception:
        conn.execute('ROLLBACK')
        conn.close()
        raise
    conn.close()


def patch_geojsons(patch: dict[str, str], geojson_dir: Path, dry_run: bool) -> None:
    """Apply raw_text corrections to all province geojson files atomically."""
    geojsons = sorted(geojson_dir.glob('inscriptions_*.geojson'))
    print(f'\nGeojsons: scanning {len(geojsons)} files')

    total_changed = 0
    for path in geojsons:
        with open(path) as f:
            data = json.load(f)

        changed = 0
        for feat in data['features']:
            eid = feat['properties'].get('edcs_id')
            if eid in patch:
                feat['properties']['raw_text'] = patch[eid]
                changed += 1

        if changed == 0:
            continue

        total_changed += changed
        print(f'  {path.name}: {changed} features updated')

        if not dry_run:
            # Write to a temp file in the same directory, then rename atomically
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
                os.replace(tmp, path)
            except Exception:
                os.unlink(tmp)
                raise

    if dry_run:
        print(f'  (dry run — no changes made; {total_changed} features would be updated)')
    else:
        print(f'  {total_changed} features updated across all geojsons')


def print_samples(patch: dict[str, str], edcs: dict[str, str], n: int = 5) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print(f'\nSample changes ({n} of {len(patch):,}):')
    shown = 0
    for eid, new_text in patch.items():
        row = conn.execute(
            'SELECT raw_text FROM inscriptions WHERE edcs_id = ?', (eid,)
        ).fetchone()
        if not row:
            continue
        print(f'  {eid}')
        print(f'    BEFORE: {repr(row["raw_text"][:100])}')
        print(f'    AFTER:  {repr(new_text[:100])}')
        shown += 1
        if shown >= n:
            break
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                        help='Actually apply changes (default is dry run)')
    args = parser.parse_args()
    dry_run = not args.apply

    if dry_run:
        print('=== DRY RUN — pass --apply to make changes ===\n')
    else:
        print('=== APPLYING CHANGES ===\n')

    edcs = load_edcs_lookup()
    patch = build_patch_map(edcs, DB_PATH)

    print(f'\nTotal DB inscriptions:  {153665:,}')
    print(f'Will be updated:        {len(patch):,}')
    print(f'Already correct / N/A:  {153665 - len(patch):,}')

    print_samples(patch, edcs)

    patch_db(patch, DB_PATH, dry_run)
    patch_geojsons(patch, GEOJSON_DIR, dry_run)

    if not dry_run:
        print('\nDone. Run `python scripts/10_build_sqlite.py` if you want to')
        print('rebuild the DB from the patched geojsons (optional — DB already patched).')


if __name__ == '__main__':
    main()
