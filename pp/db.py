from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.transaction() as conn:
            conn.executescript(SCHEMA)
            count = conn.execute("SELECT COUNT(*) FROM offboarding_reasons").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO offboarding_reasons(label, active, sort_order) VALUES (?, 1, ?)",
                    [("Keine Arbeit mehr", 10), ("Mitarbeiter passt nicht", 20), ("Leistung", 30), ("Fehlzeiten", 40), ("Sonstiges", 50)],
                )

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.transaction() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid)


def json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    custom_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS agencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    contact_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','leader')),
    department_id INTEGER REFERENCES departments(id),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    employee_code TEXT NOT NULL DEFAULT '',
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    start_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','archived')),
    notes TEXT NOT NULL DEFAULT '',
    custom_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workers_name ON workers(last_name, first_name);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL REFERENCES workers(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    assigned_from TEXT NOT NULL,
    assigned_until TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignments_worker ON assignments(worker_id);
CREATE INDEX IF NOT EXISTS idx_assignments_department ON assignments(department_id);

CREATE TABLE IF NOT EXISTS custom_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('worker','department')),
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL CHECK(field_type IN ('text','number','date','boolean','select')),
    required INTEGER NOT NULL DEFAULT 0,
    options_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    UNIQUE(entity_type, field_key)
);

CREATE TABLE IF NOT EXISTS offboarding_reasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS offboarding_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL REFERENCES workers(id),
    assignment_id INTEGER NOT NULL REFERENCES assignments(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    requested_by INTEGER NOT NULL REFERENCES users(id),
    effective_at TEXT NOT NULL,
    reason_id INTEGER REFERENCES offboarding_reasons(id),
    reason_text TEXT NOT NULL DEFAULT '',
    replacement_required INTEGER NOT NULL DEFAULT 0,
    replacement_notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('pending','sent','mail_failed','cancelled')),
    notification_to TEXT NOT NULL DEFAULT '',
    notification_subject TEXT NOT NULL DEFAULT '',
    notification_body TEXT NOT NULL DEFAULT '',
    mail_error TEXT NOT NULL DEFAULT '',
    sent_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offboarding_department ON offboarding_requests(department_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
"""
