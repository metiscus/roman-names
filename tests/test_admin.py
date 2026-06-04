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


def test_run_migrations_raises_if_flags_table_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "no_flags.db"
    monkeypatch.setenv("ROMAN_NAMES_DB", str(db_path))
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE inscriptions (edcs_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    from server import db
    with pytest.raises(sqlite3.OperationalError):
        db.run_migrations()


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
    # mark the log entry as applied
    conn = sqlite3.connect(populated_db)
    conn.execute("UPDATE edit_log SET applied_at='2026-01-01' WHERE id=1")
    conn.commit(); conn.close()
    unapplied = db.get_edit_log(unapplied_only=True)
    assert all(r["applied_at"] is None for r in unapplied)


def test_mark_edit_applied(populated_db):
    from server import db
    db.save_edit("EDCS-00000001", "summary", "updated summary")
    log = db.get_edit_log()
    assert log[0]["applied_at"] is None
    db.mark_edit_applied(log[0]["id"])
    log = db.get_edit_log()
    assert log[0]["applied_at"] is not None


def test_get_flags_filters_by_status(populated_db):
    import sqlite3
    from server import db
    conn = sqlite3.connect(populated_db)
    conn.executemany(
        "INSERT INTO flags (edcs_id, category, created_at, status) VALUES (?,?,?,?)",
        [
            ("EDCS-00000001", "people", "2026-01-01T00:00:00+00:00", "open"),
            ("EDCS-00000002", "other",  "2026-01-01T00:00:00+00:00", "resolved"),
        ]
    )
    conn.commit(); conn.close()
    open_flags = db.get_flags(status="open")
    assert len(open_flags) == 1
    assert open_flags[0]["status"] == "open"
    resolved_flags = db.get_flags(status="resolved")
    assert len(resolved_flags) == 1
    assert resolved_flags[0]["status"] == "resolved"


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
