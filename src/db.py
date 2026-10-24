"""SQLite persistence for Bargain Search: schema init and connection helper.

DB path defaults to boldtrader.db at the repo root, overridable via the
BOLDTRADER_DB environment variable. stdlib sqlite3 only, no ORM, no query layer.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "boldtrader.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bargain_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    product_identity TEXT NOT NULL,
    target_price REAL,
    queries TEXT NOT NULL DEFAULT '[]',
    exclusions TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    listing_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    bargain_search_id INTEGER NOT NULL REFERENCES bargain_searches(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    raw TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS enrichments (
    listing_id TEXT PRIMARY KEY REFERENCES listings(id),
    product TEXT,
    condition TEXT,
    bundle TEXT,
    confidence TEXT,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rejects (
    bargain_search_id INTEGER NOT NULL REFERENCES bargain_searches(id),
    listing_id TEXT NOT NULL REFERENCES listings(id),
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def db_path() -> Path:
    """Resolve the DB path: BOLDTRADER_DB env override, else repo root."""
    return Path(os.environ.get("BOLDTRADER_DB", DEFAULT_DB_PATH))


def get_connection(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced."""
    conn = sqlite3.connect(path if path is not None else db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Create all tables if missing (idempotent). Returns an open connection."""
    conn = get_connection(path)
    conn.executescript(SCHEMA)
    # Migrate DBs created before listing_ids existed.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bargain_searches)")}
    if "listing_ids" not in cols:
        conn.execute(
            "ALTER TABLE bargain_searches ADD COLUMN listing_ids TEXT NOT NULL DEFAULT '[]'"
        )
        conn.commit()
    return conn
