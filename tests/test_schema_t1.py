"""T1 schema tests (ticket #52): Product Identity, Price Observation, settings.

Covers the new tables, the added columns, the settings default, the
dropped `conversations` table, and migration idempotency for both a
fresh DB and a pre-existing (old-schema) DB.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from src.db import init_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def tables(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


# --- fresh DB ----------------------------------------------------------------


def test_new_tables_exist(db):
    assert {
        "product_identities",
        "price_observations",
        "settings",
    } <= tables(db)


def test_product_identities_columns(db):
    assert {"id", "description", "created_at", "updated_at", "deal_threshold"} == columns(
        db, "product_identities"
    )


def test_price_observations_columns(db):
    assert {
        "id",
        "listing_id",
        "product_identity_id",
        "condition",
        "effective_price",
        "observed_at",
    } == columns(db, "price_observations")


    idx_cols = [
        [r[2] for r in db.execute(f"PRAGMA index_info('{row[1]}')")]
        for row in db.execute(
            "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='price_observations'"
        )
    ]
    assert ["product_identity_id", "condition", "observed_at"] in idx_cols


def test_listings_has_product_identity_id(db):
    assert "product_identity_id" in columns(db, "listings")


def test_bargain_searches_has_product_identity_id(db):
    assert "product_identity_id" in columns(db, "bargain_searches")


def test_conversations_table_dropped(db):
    assert "conversations" not in tables(db)


def test_settings_default_deal_threshold(db):
    row = db.execute(
        "SELECT value FROM settings WHERE key='deal_threshold'"
    ).fetchone()
    assert row is not None
    assert float(row[0]) == 25.0


def test_init_is_idempotent(db):
    init_db(os.environ["BOLDTRADER_DB"])
    init_db(os.environ["BOLDTRADER_DB"])
    assert {
        "product_identities",
        "price_observations",
        "settings",
    } <= tables(db)


def test_settings_default_not_overwritten_on_reinit(db):
    db.execute("UPDATE settings SET value='40' WHERE key='deal_threshold'")
    db.commit()
    init_db(os.environ["BOLDTRADER_DB"])
    row = db.execute(
        "SELECT value FROM settings WHERE key='deal_threshold'"
    ).fetchone()
    assert float(row[0]) == 40.0


# --- pre-existing (old-schema) DB ------------------------------------------

OLD_SCHEMA = """
CREATE TABLE bargain_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    product_identity TEXT NOT NULL,
    target_price REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE conversations (
    bargain_search_id INTEGER NOT NULL REFERENCES bargain_searches(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE listings (
    id TEXT PRIMARY KEY,
    raw TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE enrichments (
    listing_id TEXT PRIMARY KEY REFERENCES listings(id),
    product TEXT,
    condition TEXT,
    bundle TEXT,
    confidence TEXT,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE rejects (
    bargain_search_id INTEGER NOT NULL REFERENCES bargain_searches(id),
    listing_id TEXT NOT NULL REFERENCES listings(id),
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def test_existing_old_db_migrates(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    seed = sqlite3.connect(path)
    seed.executescript(OLD_SCHEMA)
    seed.execute(
        "INSERT INTO bargain_searches (summary, product_identity) VALUES ('old', 'old thing')"
    )
    seed.execute("INSERT INTO listings (id, raw) VALUES ('l1', '{}')")
    seed.execute(
        "INSERT INTO conversations (bargain_search_id, role, content) VALUES (1, 'user', 'legacy')"
    )
    seed.commit()
    seed.close()

    conn = init_db(path)
    assert {"product_identities", "price_observations", "settings"} <= tables(conn)
    # and a fresh insert into the new columns works
    conn.execute(
        "INSERT INTO product_identities (description) VALUES ('HP Z440 workstation')"
    )
    conn.execute(
        "INSERT INTO price_observations (listing_id, product_identity_id, condition, effective_price, observed_at) "
        "VALUES ('l1', 1, 'complete', 250.0, '2026-10-30')"
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 1
    conn.close()
