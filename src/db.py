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
    location TEXT NOT NULL DEFAULT 'Kenmore, WA',
    queries TEXT NOT NULL DEFAULT '[]',
    exclusions TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    listing_ids TEXT NOT NULL DEFAULT '{}',
    product_identity_id INTEGER REFERENCES product_identities(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    deal_threshold REAL,
    synthesized_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL REFERENCES listings(id),
    product_identity_id INTEGER NOT NULL REFERENCES product_identities(id),
    condition TEXT NOT NULL,
    effective_price REAL NOT NULL,
    observed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_obs_identity_condition_date
    ON price_observations (product_identity_id, condition, observed_at);

CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    raw TEXT NOT NULL,
    authored_description TEXT,
    availability TEXT NOT NULL DEFAULT 'live',
    availability_checked_at TEXT,
    product_identity_id INTEGER REFERENCES product_identities(id),
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

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_messages (
    chat_session_id INTEGER NOT NULL REFERENCES chat_sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Resolve the DB path: BOLDTRADER_DB env override, else repo root."""
    return Path(os.environ.get("BOLDTRADER_DB", DEFAULT_DB_PATH))


def get_connection(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and a generous busy timeout."""
    conn = sqlite3.connect(path if path is not None else db_path(), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Create all tables if missing (idempotent). Returns an open connection."""
    conn = get_connection(path)
    conn.executescript(SCHEMA)
    # Migrate DBs created before listing_ids existed.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bargain_searches)")}
    if "listing_ids" not in cols:
        conn.execute(
            "ALTER TABLE bargain_searches ADD COLUMN listing_ids TEXT NOT NULL DEFAULT '{}'"
        )
        conn.commit()
    # Migrate DBs created before authored_description existed.
    lcols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    if "authored_description" not in lcols:
        conn.execute("ALTER TABLE listings ADD COLUMN authored_description TEXT")
        conn.commit()
    # Migrate DBs created before availability tracking existed.
    if "availability" not in lcols:
        conn.execute("ALTER TABLE listings ADD COLUMN availability TEXT NOT NULL DEFAULT 'live'")
        conn.execute("ALTER TABLE listings ADD COLUMN availability_checked_at TEXT")
        conn.commit()
    # Migrate DBs created before location existed.
    if "location" not in cols:
        conn.execute(
            "ALTER TABLE bargain_searches ADD COLUMN location TEXT NOT NULL DEFAULT 'Kenmore, WA'"
        )
        conn.commit()
    # Migrate DBs created before Product Identity mapping existed (ticket #52).
    if "product_identity_id" not in cols:
        conn.execute(
            "ALTER TABLE bargain_searches ADD COLUMN product_identity_id INTEGER REFERENCES product_identities(id)"
        )
        conn.commit()
    if "product_identity_id" not in lcols:
        conn.execute(
            "ALTER TABLE listings ADD COLUMN product_identity_id INTEGER REFERENCES product_identities(id)"
        )
        conn.commit()
    # Migrate DBs created before the living-description lifecycle (#55):
    # the synthesis timestamp on the identity, the stale-verdict list on
    # the search.
    if "stale_lids" not in cols:
        conn.execute(
            "ALTER TABLE bargain_searches ADD COLUMN stale_lids TEXT NOT NULL DEFAULT '[]'"
        )
        conn.commit()
    picols = {r[1] for r in conn.execute("PRAGMA table_info(product_identities)")}
    if "synthesized_at" not in picols:
        conn.execute("ALTER TABLE product_identities ADD COLUMN synthesized_at TEXT")
        conn.commit()
    # Drop the dead per-search transcript table (superseded by chat sessions).
    conn.execute("DROP TABLE IF EXISTS conversations")
    conn.commit()
    # Seed defaults without clobbering user-set values.
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('deal_threshold', '25')"
    )
    conn.commit()
    return conn
