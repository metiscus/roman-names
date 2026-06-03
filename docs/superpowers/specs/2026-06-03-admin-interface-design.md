# Admin Interface Design

**Date:** 2026-06-03  
**Status:** Approved

## Overview

A server-rendered HTML admin interface bolted onto the existing FastAPI app as `/admin/*` routes. Single-user, protected by a session cookie. The server never touches pipeline scripts or dataset files — all data mutations happen in SQLite, with an audit log that can be replayed offline to update CSV/parquet files.

---

## Auth & Routing

- `ADMIN_TOKEN` env var set in `passenger_wsgi.py` (not in git)
- Login form at `/admin/login` — POST checks token with `secrets.compare_digest`, sets an `HttpOnly` session cookie on success, redirects to `/admin`
- All `/admin/*` routes protected by a FastAPI dependency that validates the session cookie
- No new dependencies required

---

## Features

### Flags

- Table view: edcs_id, category, comment, email, created_at, status
- Each row links to the inscription in the public webapp
- Status field: `open` / `confirmed` / `resolved` / `spam` — settable per flag from the UI
- "Download CSV" button at `/admin/flags/export` — streams all flags including status

### Inscription Editing

- Search by EDCS ID, or navigate directly from a flag row
- Editable fields:
  - `persons` — displayed as pretty-printed JSON, saved to the `overrides` column (matching existing override logic in `db.py`)
  - `translation` — plain text
  - `summary` — plain text
- Every save writes a row to `edit_log`

### Edit Log

- Read-only table view: edcs_id, field, old_value, new_value, edited_at
- "Download CSV" button at `/admin/edit-log/export`
- Used offline to replay changes into CSV/parquet dataset files

---

## Schema Changes

Two changes applied via migration at server startup. SQLite doesn't support `IF NOT EXISTS` on `ALTER TABLE`, so migrations use a try/except to skip columns that already exist:

```sql
-- flags table additions (via try/except in Python)
ALTER TABLE flags ADD COLUMN status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE flags ADD COLUMN resolved_at TEXT;

-- new edit_log table
CREATE TABLE IF NOT EXISTS edit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    edcs_id    TEXT NOT NULL,
    field      TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    edited_at  TEXT NOT NULL,
    applied_at TEXT        -- set by apply_edit_log.py when synced to CSV files
);
```

---

## File Structure

| File | Role |
|------|------|
| `server/admin.py` | All `/admin/*` routes and auth dependency |
| `server/db.py` | New functions: `get_flags`, `update_flag_status`, `get_inscription_for_edit`, `save_edit`, `get_edit_log` |
| `server/main.py` | Registers admin router (one line change) |
| `webapp/admin.html` | Admin UI — served as static file from existing `webapp/` directory |
| `scripts/apply_edit_log.py` | Offline script: reads `edit_log` from DB, patches `data/roman_names_*.csv` files |

---

## Data Flow

```
Browser → POST /admin/inscription/{id}/edit
        → admin.py validates session
        → db.save_edit() writes overrides/translation/summary to inscriptions table
        → db.save_edit() appends row to edit_log
        → redirect back to inscription view

Offline sync (local machine only):
  python scripts/apply_edit_log.py --db roman_names.db
  → reads edit_log rows not yet applied
  → patches matching rows in data/roman_names_*.csv
  → marks log rows as applied
```

---

## Explicitly Out of Scope

- No pipeline script execution from the web server
- No parquet/GeoJSON regeneration from the web server
- No multi-user support (single token, no user accounts)
- No inline translation/summary regeneration via LLM
