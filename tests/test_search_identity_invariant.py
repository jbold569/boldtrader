"""Search ⇒ Product Identity invariant (ticket #61).

Every Bargain Search maps to exactly one Product Identity — no unmapped
searches. Creation seeds/mints the identity from the draft phrase (the
existing seed function); the update handler backfills any legacy NULL
mapping; init_db backfills existing NULL rows at startup.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.db import init_db

DRAFT = {
    "summary": "clean workstations",
    "product_identity": "HP Z440 workstation",
    "queries": ["hp z440"],
    "exclusions": ["no monitors"],
    "target_price": 300.0,
    "location": "Kenmore, WA",
}


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "inv.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    init_db(path).close()

    from src import server as server_mod

    server_mod.Handler.marketplaces = {}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "offerup"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "inv.db"))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return exc.code, parsed


def test_create_search_seeds_mapped_identity(site, db):
    status, body = call("POST", f"{site}/api/v1/searches", DRAFT)
    assert status == 201
    row = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?",
        (body["id"],),
    ).fetchone()
    assert row[0] is not None
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (row[0],)
    ).fetchone()[0]
    assert desc == "HP Z440 workstation"


def test_create_search_reuses_existing_identity(site, db):
    status, body = call("POST", f"{site}/api/v1/searches", DRAFT)
    first = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?",
        (body["id"],),
    ).fetchone()[0]
    status2, body2 = call("POST", f"{site}/api/v1/searches", DRAFT)
    second = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?",
        (body2["id"],),
    ).fetchone()[0]
    assert second == first
    n = db.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0]
    assert n == 1


def test_update_search_backfills_null_mapping(site, db):
    cur = db.execute(
        "INSERT INTO bargain_searches (summary, product_identity, location, "
        "target_price, queries, exclusions, listing_ids, product_identity_id) "
        "VALUES ('legacy', 'legacy phrase', 'Kenmore, WA', 100.0, '[\"legacy q\"]', '[]', '{}', NULL)"
    )
    db.commit()
    sid = cur.lastrowid
    status, body = call("PATCH", f"{site}/api/v1/searches/{sid}",
                       {"product_identity": "fixed phrase"})
    assert status == 200
    row = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] is not None
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (row[0],)
    ).fetchone()[0]
    assert desc == "fixed phrase"


LEGACY_SCHEMA = """
CREATE TABLE bargain_searches (
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
"""


def test_init_backfills_unmapped_searches(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    seed = sqlite3.connect(path)
    seed.executescript(LEGACY_SCHEMA)
    seed.execute(
        "INSERT INTO bargain_searches (summary, product_identity) VALUES ('a', 'alpha thing')"
    )
    seed.execute(
        "INSERT INTO bargain_searches (summary, product_identity) VALUES ('b', 'beta thing')"
    )
    seed.commit()
    seed.close()

    conn = init_db(path)
    rows = conn.execute(
        "SELECT s.id, p.description FROM bargain_searches s "
        "JOIN product_identities p ON p.id = s.product_identity_id ORDER BY s.id"
    ).fetchall()
    assert rows == [(1, "alpha thing"), (2, "beta thing")]
    conn.close()


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "legacy2.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    seed = sqlite3.connect(path)
    seed.executescript(LEGACY_SCHEMA)
    seed.execute(
        "INSERT INTO bargain_searches (summary, product_identity) VALUES ('a', 'alpha thing')"
    )
    seed.commit()
    seed.close()
    init_db(path).close()
    conn = init_db(path)
    n = conn.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0]
    assert n == 1
    conn.close()
