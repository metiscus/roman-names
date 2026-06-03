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
