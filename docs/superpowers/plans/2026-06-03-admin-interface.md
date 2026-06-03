# Admin Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a password-protected `/admin` section to the existing FastAPI app with flag management, inscription editing, and an audit log.

**Architecture:** Server-rendered HTML routes in a new `server/admin.py` module; all mutations go to SQLite with an `edit_log` table; no pipeline scripts run on the server. A separate offline script `scripts/apply_edit_log.py` replays edits into the dataset files.

**Tech Stack:** FastAPI, SQLite, Python stdlib (`hmac`, `csv`, `io`, `secrets`), no new dependencies.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `tests/conftest.py` | Add `edit_log` table + new `flags` columns to test fixture |
| Modify | `tests/test_api.py` | Fix `test_tiles_translation_in_response` (field renamed to `has_translation`) |
| Create | `tests/test_admin.py` | All admin endpoint tests |
| Modify | `server/db.py` | `run_migrations()` + 5 new query functions |
| Create | `server/admin.py` | All `/admin/*` routes, session auth, HTML rendering |
| Modify | `server/main.py` | Call `run_migrations()` at startup, include admin router |
| Create | `scripts/apply_edit_log.py` | Offline: reads `edit_log`, patches `enrichment_*.json` and `inscriptions_*.geojson` |

---

## Task 1: Fix broken test + update conftest schema

The earlier payload-minification change renamed `translation` to `has_translation` in tile responses, breaking an existing test. Also update the `test_db` fixture to include the new admin schema so subsequent tasks can test against it.

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Fix the broken tile test**

In `tests/test_api.py`, replace:
```python
def test_tiles_translation_in_response(client):
    resp = client.get("/api/tiles/10/541/398")
    assert resp.status_code == 200
    features = resp.json()["features"]
    feat = next(f for f in features if f["properties"]["edcs_id"] == "EDCS-00000002")
    assert feat["properties"]["translation"] == "Translation for inscription 2"
```
with:
```python
def test_tiles_has_translation_flag(client):
    resp = client.get("/api/tiles/10/541/398")
    assert resp.status_code == 200
    features = resp.json()["features"]
    feat = next(f for f in features if f["properties"]["edcs_id"] == "EDCS-00000002")
    assert feat["properties"]["has_translation"] is True

def test_tiles_no_translation_flag_false(client):
    resp = client.get("/api/tiles/10/541/399")
    assert resp.status_code == 200
    features = resp.json()["features"]
    feat = next(f for f in features if f["properties"]["edcs_id"] == "EDCS-00000001")
    assert feat["properties"]["has_translation"] is False
```

- [ ] **Step 2: Update conftest to include admin schema**

In `tests/conftest.py`, change the `flags` table definition and add `edit_log` inside the `executescript` call:

```python
# Replace the flags CREATE TABLE with this:
        CREATE TABLE flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edcs_id TEXT NOT NULL, category TEXT NOT NULL,
            comment TEXT, email TEXT, created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            resolved_at TEXT
        );
        CREATE TABLE edit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edcs_id TEXT NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            edited_at TEXT NOT NULL,
            applied_at TEXT
        );
```

- [ ] **Step 3: Run existing tests to confirm only the renamed test was broken**

```bash
pytest tests/test_api.py -v
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api.py tests/conftest.py
git commit -m "fix: rename translation tile field to has_translation in tests; add admin schema to fixture"
```

---

## Task 2: Schema migration in db.py

Add `run_migrations()` to `server/db.py`. It is idempotent — safe to call every startup. Adds `status`/`resolved_at` to `flags` (existing production DB) and creates `edit_log`.

**Files:**
- Modify: `server/db.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_admin.py`:
```python
import sqlite3
import pytest


@pytest.fixture
def admin_db(tmp_path, monkeypatch):
    """Fresh DB with only the pre-migration schema (simulates existing production DB)."""
    db_path = tmp_path / "migration_test.db"
    monkeypatch.setenv("ROMAN_NAMES_DB", str(db_path))
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE inscriptions (
            edcs_id TEXT PRIMARY KEY, province TEXT NOT NULL,
            lat REAL NOT NULL, lon REAL NOT NULL,
            findspot TEXT, raw_text TEXT,
            date_from INTEGER, date_to INTEGER,
            persons TEXT NOT NULL, overrides TEXT,
            translation TEXT, summary TEXT,
            tile_x INTEGER NOT NULL DEFAULT 0,
            tile_y INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edcs_id TEXT NOT NULL, category TEXT NOT NULL,
            comment TEXT, email TEXT, created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def test_run_migrations_adds_flags_columns(admin_db):
    from server import db
    db.run_migrations()
    conn = sqlite3.connect(admin_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(flags)")}
    conn.close()
    assert "status" in cols
    assert "resolved_at" in cols


def test_run_migrations_creates_edit_log(admin_db):
    from server import db
    db.run_migrations()
    conn = sqlite3.connect(admin_db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "edit_log" in tables


def test_run_migrations_is_idempotent(admin_db):
    from server import db
    db.run_migrations()
    db.run_migrations()  # should not raise
```

- [ ] **Step 2: Run to confirm it fails**

```bash
pytest tests/test_admin.py::test_run_migrations_adds_flags_columns -v
```
Expected: FAIL with `AttributeError: module 'server.db' has no attribute 'run_migrations'`

- [ ] **Step 3: Implement run_migrations in server/db.py**

Add after the imports at the top of `server/db.py`:
```python
def run_migrations() -> None:
    """Idempotent — call at every startup."""
    with _conn() as conn:
        for ddl in [
            "ALTER TABLE flags ADD COLUMN status TEXT NOT NULL DEFAULT 'open'",
            "ALTER TABLE flags ADD COLUMN resolved_at TEXT",
        ]:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
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
```

- [ ] **Step 4: Run migration tests**

```bash
pytest tests/test_admin.py -k "migration" -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/db.py tests/test_admin.py
git commit -m "feat: add run_migrations() for edit_log table and flags status columns"
```

---

## Task 3: New DB query functions

Add the five functions the admin routes will call. All go in `server/db.py`.

**Files:**
- Modify: `server/db.py`
- Modify: `tests/test_admin.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_admin.py`:
```python
import json


@pytest.fixture
def populated_db(test_db, monkeypatch):
    """Reuse the main test_db fixture (already has inscriptions + flags schema)."""
    return test_db


def test_get_flags_empty(populated_db):
    from server import db
    assert db.get_flags() == []


def test_get_flags_returns_inserted(populated_db):
    import sqlite3
    from server import db
    conn = sqlite3.connect(populated_db)
    conn.execute(
        "INSERT INTO flags (edcs_id, category, comment, email, created_at, status) VALUES (?,?,?,?,?,?)",
        ("EDCS-00000001", "people", "wrong name", "a@b.com", "2026-01-01T00:00:00+00:00", "open"),
    )
    conn.commit(); conn.close()
    flags = db.get_flags()
    assert len(flags) == 1
    assert flags[0]["edcs_id"] == "EDCS-00000001"
    assert flags[0]["status"] == "open"


def test_update_flag_status(populated_db):
    import sqlite3
    from server import db
    conn = sqlite3.connect(populated_db)
    conn.execute(
        "INSERT INTO flags (edcs_id, category, created_at, status) VALUES (?,?,?,?)",
        ("EDCS-00000001", "other", "2026-01-01T00:00:00+00:00", "open"),
    )
    conn.commit()
    flag_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    db.update_flag_status(flag_id, "resolved")
    flags = db.get_flags()
    assert flags[0]["status"] == "resolved"
    assert flags[0]["resolved_at"] is not None


def test_get_inscription_for_edit(populated_db):
    from server import db
    insc = db.get_inscription_for_edit("EDCS-00000001")
    assert insc is not None
    assert insc["edcs_id"] == "EDCS-00000001"
    assert "persons" in insc
    assert "overrides" in insc
    assert "translation" in insc
    assert "summary" in insc


def test_get_inscription_for_edit_not_found(populated_db):
    from server import db
    assert db.get_inscription_for_edit("EDCS-NOTEXIST") is None


def test_save_edit_translation(populated_db):
    from server import db
    db.save_edit("EDCS-00000001", "translation", "New translation text")
    insc = db.get_inscription_for_edit("EDCS-00000001")
    assert insc["translation"] == "New translation text"
    log = db.get_edit_log()
    assert len(log) == 1
    assert log[0]["field"] == "translation"
    assert log[0]["new_value"] == "New translation text"


def test_save_edit_persons_writes_overrides(populated_db):
    from server import db
    new_persons = json.dumps([{"praenomen": "Gaius", "nomen": "Julius"}])
    db.save_edit("EDCS-00000001", "persons", new_persons)
    import sqlite3
    conn = sqlite3.connect(populated_db)
    row = conn.execute("SELECT overrides FROM inscriptions WHERE edcs_id='EDCS-00000001'").fetchone()
    conn.close()
    assert row[0] == new_persons


def test_save_edit_unknown_field_raises(populated_db):
    from server import db
    with pytest.raises(ValueError):
        db.save_edit("EDCS-00000001", "bad_field", "value")


def test_get_edit_log_unapplied_only(populated_db):
    from server import db
    import sqlite3
    db.save_edit("EDCS-00000001", "summary", "new summary")
    # mark first log entry as applied
    conn = sqlite3.connect(populated_db)
    conn.execute("UPDATE edit_log SET applied_at='2026-01-01' WHERE id=1")
    conn.commit(); conn.close()
    unapplied = db.get_edit_log(unapplied_only=True)
    assert all(r["applied_at"] is None for r in unapplied)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_admin.py -k "not migration" -v
```
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement the five functions in server/db.py**

Add after `run_migrations()`:
```python
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
```

- [ ] **Step 4: Run all admin DB tests**

```bash
pytest tests/test_admin.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add server/db.py tests/test_admin.py
git commit -m "feat: add admin DB functions (flags, edit log, inscription edit)"
```

---

## Task 4: Admin routes — auth, flags, inscription edit, edit log

Create `server/admin.py` with all `/admin/*` routes. HTML is rendered inline (f-strings); no Jinja2 required.

**Files:**
- Create: `server/admin.py`
- Modify: `tests/test_admin.py`

- [ ] **Step 1: Write failing tests for auth**

Append to `tests/test_admin.py`:
```python
import os
from fastapi.testclient import TestClient


@pytest.fixture
def admin_client(test_db, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-secret-token")
    from server.main import app
    return TestClient(app, follow_redirects=False)


def test_admin_login_page_loads(admin_client):
    resp = admin_client.get("/admin/login")
    assert resp.status_code == 200
    assert b"Login" in resp.content


def test_admin_flags_redirects_unauthenticated(admin_client):
    resp = admin_client.get("/admin/flags")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_admin_login_wrong_token(admin_client):
    resp = admin_client.post("/admin/login", data={"token": "wrong"}, follow_redirects=False)
    assert resp.status_code == 200
    assert b"Invalid token" in resp.content


def test_admin_login_correct_token_sets_cookie(admin_client):
    resp = admin_client.post("/admin/login", data={"token": "test-secret-token"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/flags"
    assert "roman_admin" in resp.cookies


@pytest.fixture
def authed_client(admin_client):
    admin_client.post("/admin/login", data={"token": "test-secret-token"}, follow_redirects=False)
    return admin_client


def test_admin_flags_page_loads_when_authed(authed_client):
    resp = authed_client.get("/admin/flags")
    assert resp.status_code == 200
    assert b"Flags" in resp.content


def test_admin_logout_clears_cookie(authed_client):
    resp = authed_client.get("/admin/logout", follow_redirects=False)
    assert resp.status_code == 303
    resp2 = authed_client.get("/admin/flags", follow_redirects=False)
    assert resp2.status_code == 303  # redirected back to login


def test_admin_flags_export_csv(authed_client, test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    conn.execute(
        "INSERT INTO flags (edcs_id, category, created_at, status) VALUES (?,?,?,?)",
        ("EDCS-00000001", "people", "2026-01-01T00:00:00+00:00", "open"),
    )
    conn.commit(); conn.close()
    resp = authed_client.get("/admin/flags/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert b"edcs_id" in resp.content
    assert b"EDCS-00000001" in resp.content


def test_admin_flag_status_update(authed_client, test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    conn.execute(
        "INSERT INTO flags (edcs_id, category, created_at, status) VALUES (?,?,?,?)",
        ("EDCS-00000001", "other", "2026-01-01T00:00:00+00:00", "open"),
    )
    conn.commit()
    flag_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    resp = authed_client.post(f"/admin/flags/{flag_id}/status", data={"status": "resolved"}, follow_redirects=False)
    assert resp.status_code == 303
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT status FROM flags WHERE id=?", (flag_id,)).fetchone()
    conn.close()
    assert row[0] == "resolved"


def test_admin_inscription_edit_page(authed_client):
    resp = authed_client.get("/admin/inscription/EDCS-00000001")
    assert resp.status_code == 200
    assert b"EDCS-00000001" in resp.content
    assert b"translation" in resp.content.lower()


def test_admin_inscription_edit_saves(authed_client, test_db):
    import sqlite3
    resp = authed_client.post(
        "/admin/inscription/EDCS-00000001/edit",
        data={"persons": "[]", "translation": "Updated translation", "summary": "Updated summary"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT translation FROM inscriptions WHERE edcs_id='EDCS-00000001'").fetchone()
    conn.close()
    assert row[0] == "Updated translation"


def test_admin_inscription_edit_invalid_json(authed_client):
    resp = authed_client.post(
        "/admin/inscription/EDCS-00000001/edit",
        data={"persons": "not json", "translation": "", "summary": ""},
    )
    assert resp.status_code == 200
    assert b"Invalid JSON" in resp.content


def test_admin_edit_log_page(authed_client, test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    conn.execute(
        "INSERT INTO edit_log (edcs_id, field, old_value, new_value, edited_at) VALUES (?,?,?,?,?)",
        ("EDCS-00000001", "translation", "old", "new", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit(); conn.close()
    resp = authed_client.get("/admin/edit-log")
    assert resp.status_code == 200
    assert b"EDCS-00000001" in resp.content


def test_admin_edit_log_export_csv(authed_client, test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    conn.execute(
        "INSERT INTO edit_log (edcs_id, field, old_value, new_value, edited_at) VALUES (?,?,?,?,?)",
        ("EDCS-00000001", "summary", "old summary", "new summary", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit(); conn.close()
    resp = authed_client.get("/admin/edit-log/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert b"edcs_id" in resp.content
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_admin.py -k "admin_login or admin_flags or admin_inscription or admin_edit_log or admin_logout" -v
```
Expected: FAIL with import errors (admin module doesn't exist yet).

- [ ] **Step 3: Create server/admin.py**

```python
import csv
import hashlib
import hmac
import io
import json
import os
import secrets

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from . import db

router = APIRouter(prefix="/admin")
COOKIE_NAME = "roman_admin"
_STATUS_OPTS = ("open", "confirmed", "resolved", "spam")
_STATUS_COLORS = {
    "open": "#6c757d", "confirmed": "#856404",
    "resolved": "#155724", "spam": "#721c24",
}


# ── Session helpers ───────────────────────────────────────────────────────────

def _session_token() -> str:
    raw = os.environ.get("ADMIN_TOKEN", "")
    return hmac.new(raw.encode(), b"roman-names-admin", hashlib.sha256).hexdigest()


def _check(session: str | None) -> bool:
    raw = os.environ.get("ADMIN_TOKEN", "")
    if not raw or not session:
        return False
    return secrets.compare_digest(session, _session_token())


def _require(session: str | None) -> None:
    if not _check(session):
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})


# ── HTML shell ────────────────────────────────────────────────────────────────

def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Admin — {title}</title>
<style>
body{{font-family:-apple-system,sans-serif;margin:0;background:#f8f9fa;color:#2c3e50}}
nav{{background:#2c3e50;padding:10px 20px;display:flex;gap:20px;align-items:center}}
nav a{{color:#adb5bd;text-decoration:none;font-size:.9rem}}nav a:hover{{color:#fff}}
nav strong{{color:#fff;margin-right:20px}}
main{{padding:20px;max-width:1200px;margin:0 auto}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden;
       box-shadow:0 1px 4px rgba(0,0,0,.1);margin-bottom:20px}}
th{{background:#f0f0f0;text-align:left;padding:8px 12px;font-size:.82rem}}
td{{padding:8px 12px;border-top:1px solid #eee;font-size:.85rem;vertical-align:top}}
.btn{{padding:4px 10px;border-radius:4px;border:none;cursor:pointer;font-size:.82rem;
      text-decoration:none;display:inline-block}}
.btn-primary{{background:#c0392b;color:#fff}}.btn-secondary{{background:#6c757d;color:#fff}}
.btn-sm{{padding:2px 8px;font-size:.78rem}}
form.inline{{display:inline}}
input,textarea,select{{width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;
                       font-size:.88rem;box-sizing:border-box}}
textarea{{font-family:monospace;font-size:.82rem;resize:vertical}}
.card{{background:#fff;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.1);
       padding:20px;margin-bottom:20px}}
h1{{font-size:1.3rem;margin:0 0 16px}}
.flash-ok{{background:#d4edda;color:#155724;padding:10px 16px;border-radius:4px;
           margin-bottom:16px;font-size:.88rem}}
.flash-err{{background:#f8d7da;color:#721c24;padding:10px 16px;border-radius:4px;
            margin-bottom:16px;font-size:.88rem}}
.toolbar{{display:flex;gap:8px;margin-bottom:16px;align-items:center}}
.sel-inline{{width:auto;padding:2px 6px}}
</style>
</head>
<body>
<nav>
  <strong>Roman Names Admin</strong>
  <a href="/admin/flags">Flags</a>
  <a href="/admin/inscription">Inscriptions</a>
  <a href="/admin/edit-log">Edit Log</a>
  <a href="/admin/logout">Logout</a>
</nav>
<main>{content}</main>
</body>
</html>""")


# ── Login / logout ────────────────────────────────────────────────────────────

def _login_form(error: str = "") -> str:
    err_html = f'<div class="flash-err">{error}</div>' if error else ""
    return f"""
<div class="card" style="max-width:360px;margin:60px auto">
  <h1>Login</h1>
  {err_html}
  <form method="post" action="/admin/login">
    <div style="margin-bottom:12px">
      <label style="display:block;font-size:.85rem;margin-bottom:4px">Admin token</label>
      <input type="password" name="token" autofocus required>
    </div>
    <button class="btn btn-primary" type="submit">Sign in</button>
  </form>
</div>"""


@router.get("/login", response_class=HTMLResponse)
def login_get():
    return _page("Login", _login_form())


@router.post("/login")
def login_post(token: str = Form(...)):
    raw = os.environ.get("ADMIN_TOKEN", "")
    if not raw or not secrets.compare_digest(token, raw):
        return _page("Login", _login_form("Invalid token."))
    resp = RedirectResponse("/admin/flags", status_code=303)
    resp.set_cookie(COOKIE_NAME, _session_token(), httponly=True, samesite="lax")
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── Flags ─────────────────────────────────────────────────────────────────────

@router.get("/flags", response_class=HTMLResponse)
def flags_list(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    flags = db.get_flags()
    rows = ""
    for f in flags:
        color = _STATUS_COLORS.get(f["status"], "#000")
        opts = "".join(
            f'<option value="{s}"{"selected" if s == f["status"] else ""}>{s}</option>'
            for s in _STATUS_OPTS
        )
        rows += f"""<tr>
  <td><a href="/admin/inscription/{f['edcs_id']}">{f['edcs_id']}</a></td>
  <td>{f['category']}</td>
  <td style="max-width:260px">{f.get('comment') or ''}</td>
  <td>{f.get('email') or ''}</td>
  <td>{f['created_at'][:10]}</td>
  <td style="color:{color};font-weight:600">{f['status']}</td>
  <td>
    <form class="inline" method="post" action="/admin/flags/{f['id']}/status">
      <select class="sel-inline" name="status">{opts}</select>
      <button class="btn btn-sm btn-secondary" type="submit">Set</button>
    </form>
    <a class="btn btn-sm" href="/#edcs_id={f['edcs_id']}" target="_blank">View</a>
  </td>
</tr>"""
    content = f"""
<div class="toolbar">
  <h1 style="margin:0;flex:1">Flags ({len(flags)})</h1>
  <a class="btn btn-secondary" href="/admin/flags/export">Download CSV</a>
</div>
<table>
  <thead><tr>
    <th>EDCS ID</th><th>Category</th><th>Comment</th><th>Email</th>
    <th>Date</th><th>Status</th><th>Actions</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    return _page("Flags", content)


@router.post("/flags/{flag_id}/status")
def flag_set_status(
    flag_id: int,
    status: str = Form(...),
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    if status not in _STATUS_OPTS:
        raise HTTPException(400, "Invalid status")
    db.update_flag_status(flag_id, status)
    return RedirectResponse("/admin/flags", status_code=303)


@router.get("/flags/export")
def flags_export(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "edcs_id", "category", "comment", "email",
                    "created_at", "status", "resolved_at"],
    )
    writer.writeheader()
    writer.writerows(db.get_flags())
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flags.csv"},
    )


# ── Inscription edit ──────────────────────────────────────────────────────────

@router.get("/inscription", response_class=HTMLResponse)
def inscription_search(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    return _page("Edit Inscription", """
<div class="card" style="max-width:480px">
  <h1>Edit Inscription</h1>
  <form method="get" action="/admin/inscription/search">
    <div style="display:flex;gap:8px">
      <input name="q" placeholder="EDCS-12345678" style="flex:1">
      <button class="btn btn-primary" type="submit">Load</button>
    </div>
  </form>
</div>""")


@router.get("/inscription/search")
def inscription_search_redirect(
    q: str = "",
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    return RedirectResponse(f"/admin/inscription/{q.strip().upper()}", status_code=303)


@router.get("/inscription/{edcs_id}", response_class=HTMLResponse)
def inscription_edit_get(
    edcs_id: str,
    saved: str = "",
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    insc = db.get_inscription_for_edit(edcs_id)
    if insc is None:
        return _page("Not Found", f'<div class="flash-err">Inscription {edcs_id} not found.</div>')

    persons_raw = insc["overrides"] or insc["persons"] or "[]"
    try:
        persons_display = json.dumps(json.loads(persons_raw), indent=2)
    except Exception:
        persons_display = persons_raw

    flash = '<div class="flash-ok">Saved successfully.</div>' if saved == "1" else ""
    raw_block = ""
    if insc.get("raw_text"):
        raw_block = (
            "<details style='margin-bottom:16px'>"
            "<summary style='cursor:pointer;font-size:.82rem;color:#6c757d'>Raw inscription text</summary>"
            f"<pre style='font-size:.78rem;background:#f8f9fa;padding:10px;border-radius:4px;"
            f"white-space:pre-wrap'>{insc['raw_text']}</pre></details>"
        )

    content = f"""{flash}
<div class="card">
  <h1>Edit: {edcs_id}</h1>
  <p style="color:#6c757d;font-size:.85rem;margin-bottom:12px">{insc.get('findspot') or ''}</p>
  {raw_block}
  <form method="post" action="/admin/inscription/{edcs_id}/edit">
    <div style="margin-bottom:16px">
      <label style="font-weight:600;font-size:.85rem;display:block;margin-bottom:4px">
        Persons JSON (saved to overrides column)
      </label>
      <textarea name="persons" rows="10">{persons_display}</textarea>
    </div>
    <div style="margin-bottom:16px">
      <label style="font-weight:600;font-size:.85rem;display:block;margin-bottom:4px">Translation</label>
      <textarea name="translation" rows="4">{insc.get('translation') or ''}</textarea>
    </div>
    <div style="margin-bottom:16px">
      <label style="font-weight:600;font-size:.85rem;display:block;margin-bottom:4px">Summary</label>
      <textarea name="summary" rows="3">{insc.get('summary') or ''}</textarea>
    </div>
    <button class="btn btn-primary" type="submit">Save changes</button>
    <a class="btn btn-secondary" href="/#edcs_id={edcs_id}" target="_blank"
       style="margin-left:8px">View on map ↗</a>
  </form>
</div>"""
    return _page(f"Edit {edcs_id}", content)


@router.post("/inscription/{edcs_id}/edit")
def inscription_edit_post(
    edcs_id: str,
    persons: str = Form(""),
    translation: str = Form(""),
    summary: str = Form(""),
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    insc = db.get_inscription_for_edit(edcs_id)
    if insc is None:
        raise HTTPException(404)

    try:
        json.loads(persons)
    except json.JSONDecodeError:
        return _page(
            "Edit Error",
            f'<div class="flash-err">Invalid JSON in persons field.</div>'
            f'<a href="/admin/inscription/{edcs_id}">← Back</a>',
        )

    # Only log fields that actually changed
    current_persons = insc["overrides"] or insc["persons"] or "[]"
    if persons != current_persons:
        db.save_edit(edcs_id, "persons", persons or None)
    if translation != (insc.get("translation") or ""):
        db.save_edit(edcs_id, "translation", translation or None)
    if summary != (insc.get("summary") or ""):
        db.save_edit(edcs_id, "summary", summary or None)

    return RedirectResponse(f"/admin/inscription/{edcs_id}?saved=1", status_code=303)


# ── Edit log ──────────────────────────────────────────────────────────────────

@router.get("/edit-log", response_class=HTMLResponse)
def edit_log_list(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    rows_data = db.get_edit_log()
    rows = ""
    for r in rows_data:
        applied = r.get("applied_at") or ""
        rows += f"""<tr>
  <td><a href="/admin/inscription/{r['edcs_id']}">{r['edcs_id']}</a></td>
  <td>{r['field']}</td>
  <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
      title="{r.get('old_value') or ''}">{(r.get('old_value') or '')[:60]}</td>
  <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
      title="{r.get('new_value') or ''}">{(r.get('new_value') or '')[:60]}</td>
  <td>{r['edited_at'][:16]}</td>
  <td>{"✓ " + applied[:10] if applied else "—"}</td>
</tr>"""
    content = f"""
<div class="toolbar">
  <h1 style="margin:0;flex:1">Edit Log ({len(rows_data)} entries)</h1>
  <a class="btn btn-secondary" href="/admin/edit-log/export">Download CSV</a>
</div>
<table>
  <thead><tr>
    <th>EDCS ID</th><th>Field</th><th>Old Value</th><th>New Value</th>
    <th>Edited At</th><th>Applied</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    return _page("Edit Log", content)


@router.get("/edit-log/export")
def edit_log_export(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "edcs_id", "field", "old_value", "new_value",
                    "edited_at", "applied_at"],
    )
    writer.writeheader()
    writer.writerows(db.get_edit_log())
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=edit_log.csv"},
    )
```

- [ ] **Step 4: Run all admin tests**

```bash
pytest tests/test_admin.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add server/admin.py tests/test_admin.py
git commit -m "feat: add admin routes (auth, flags, inscription edit, edit log)"
```

---

## Task 5: Wire up router and startup migration in main.py

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1: Update main.py**

Replace the contents of `server/main.py` with:
```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .admin import router as admin_router
from .models import FlagRequest

WEBAPP_DIR = Path(__file__).parent.parent / "webapp"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.run_migrations()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(admin_router)


@app.middleware("http")
async def cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/tiles/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/tiles/{z}/{x}/{y}")
def tiles(z: int, x: int, y: int):
    data = db.get_markers_for_tile(z, x, y)
    response = JSONResponse(content=data)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/api/inscription/{edcs_id}")
def inscription(edcs_id: str):
    result = db.get_inscription(edcs_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Inscription not found")
    return result


@app.post("/api/flags")
def flag(req: FlagRequest):
    db.insert_flag(req.edcs_id, req.category, req.comment, req.email)
    return {"ok": True}


# Static files mount must come last
app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="static")
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add server/main.py
git commit -m "feat: register admin router and run migrations at startup"
```

---

## Task 6: apply_edit_log.py offline sync script

Reads unapplied `edit_log` rows from the DB and patches:
- `webapp/data/enrichment_*.json` for `translation` and `summary` edits
- `webapp/data/inscriptions_*.geojson` for `persons` edits

Marks each row `applied_at` after patching. Does not touch CSV files (persons edits require re-running clustering — out of scope).

**Files:**
- Create: `scripts/apply_edit_log.py`

- [ ] **Step 1: Create the script**

```python
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
```

- [ ] **Step 2: Smoke test the script against the live DB (dry run)**

```bash
python scripts/apply_edit_log.py --dry-run
```
Expected: "No unapplied edits found." (or a dry-run summary if edits exist).

- [ ] **Step 3: Commit**

```bash
git add scripts/apply_edit_log.py
git commit -m "feat: add apply_edit_log.py offline sync script"
```

---

## Notes

- **Webapp improvements** (`webapp_improvements.md`) are a separate plan — implement after this one is complete and tested.
- **CSV patching for persons edits**: `apply_edit_log.py` does not update `roman_names_*.csv` for persons changes because those files store individual name components across multiple rows per inscription; applying an override would require re-running the clustering pipeline. The override is correctly stored in the DB `overrides` column and the GeoJSON file.
- **ADMIN_TOKEN on Dreamhost**: set in `passenger_wsgi.py` as `os.environ["ADMIN_TOKEN"] = "your-token-here"`. This file is not checked into git.
