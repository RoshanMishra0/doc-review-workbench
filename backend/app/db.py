"""SQLite storage. One file, created on first start; work survives restarts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_version INTEGER NOT NULL,
    sample_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_processed_at TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT,
    kind TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT,
    status TEXT NOT NULL,
    status_detail TEXT,
    rejection_code TEXT,
    layout_id TEXT,
    page_count INTEGER,
    sheet_name TEXT,
    header_row INTEGER,
    mapping_json TEXT,
    date_order TEXT,
    default_currency TEXT,
    mapping_profile_id INTEGER,
    record_count INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT NOT NULL,
    processed_at TEXT,
    removed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_batch ON files(batch_id);

CREATE TABLE IF NOT EXISTS file_pages (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (file_id, page_no)
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_page INTEGER,
    source_row INTEGER,
    extraction_method TEXT NOT NULL,
    date_order TEXT NOT NULL,
    extracted_json TEXT NOT NULL,
    source_cells_json TEXT,
    notes_json TEXT NOT NULL DEFAULT '[]',
    corrections_json TEXT NOT NULL DEFAULT '{}',
    fields_json TEXT,
    checks_json TEXT,
    validation_status TEXT,
    match_status TEXT,
    match_json TEXT,
    partner_id INTEGER,
    review_status TEXT NOT NULL DEFAULT 'awaiting_review',
    review_reason TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_batch ON records(batch_id);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    rule_id TEXT,
    field TEXT,
    severity TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issues_record ON issues(record_id);
CREATE INDEX IF NOT EXISTS idx_issues_batch ON issues(batch_id);

CREATE TABLE IF NOT EXISTS manual_links (
    record_id INTEGER PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
    reference_id INTEGER NOT NULL UNIQUE REFERENCES records(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    record_id INTEGER,
    file_id INTEGER,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    note TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_batch ON history(batch_id);
CREATE INDEX IF NOT EXISTS idx_history_record ON history(record_id);

CREATE TABLE IF NOT EXISTS mapping_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    template_id TEXT NOT NULL,
    role TEXT NOT NULL,
    header_signature TEXT NOT NULL,
    headers_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    date_order TEXT NOT NULL,
    default_currency TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a database created by an older version up to the current schema. Idempotent."""
    columns = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    if "removed_at" not in columns:  # schema 1 -> 2
        conn.execute("ALTER TABLE files ADD COLUMN removed_at TEXT")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)


def log_history(conn: sqlite3.Connection, batch_id: int, action: str, *, actor: str = "reviewer",
                record_id: int | None = None, file_id: int | None = None, field: str | None = None,
                old_value: str | None = None, new_value: str | None = None, note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO history (batch_id, record_id, file_id, action, field, old_value, new_value, note, actor, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (batch_id, record_id, file_id, action, field, old_value, new_value, note, actor, now_iso()),
    )
