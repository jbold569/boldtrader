"""Rejection as a live correction to Product Identity data (ticket #61).

A rejection is not just an exclusion note for the next sift: it is a
correction. One transaction: the reject row, the deletion of that
listing's price observations under the search's mapped identity, and the
reason appended verbatim to the Exclusions block of that identity's
description. Restore reverses all three.

Rejection core is tested function-level against a temp DB (the
test_reenrich.py seam); restore goes through the live-server fixture
because its handler takes an HTTP handler.
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
from src import enhanced


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB; nothing external."""
    path = tmp_path / "rej.db"
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
    """The same temp DB the server reads, for seeding and asserting.
    init_db is idempotent, so running it before an already-initialized
    file is harmless."""
    path = tmp_path / "rej.db"
    init_db(path).close()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def seed_identity(conn, description="HP Z440 workstation"):
    cur = conn.execute(
        "INSERT INTO product_identities (description) VALUES (?)", (description,)
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid, price=100.0, identity_id=None, condition="complete"):
    raw = {
        "id": lid,
        "title": f"Listing {lid}",
        "price": price,
        "marketplace": "offerup",
        "url": f"https://example.invalid/{lid}",
    }
    conn.execute(
        "INSERT INTO listings (id, raw, product_identity_id) VALUES (?, ?, ?)",
        (lid, json.dumps(raw), identity_id),
    )
    conn.commit()


def seed_search(conn, identity_id=None):
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, product_identity_id) "
        "VALUES ('s', 'p', ?)",
        (identity_id,),
    )
    conn.commit()
    return cur.lastrowid


def seed_obs(conn, lid, pid, price=100.0, day="2026-10-01"):
    conn.execute(
        "INSERT INTO price_observations "
        "(listing_id, product_identity_id, condition, effective_price, observed_at) "
        "VALUES (?, ?, 'complete', ?, ?)",
        (lid, pid, price, day),
    )
    conn.commit()


# --- rejection: insert + observation delete + exclusion append ----------------


def test_reject_records_rejection(db):
    pid = seed_identity(db)
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    enhanced.reject_listing(db, sid, "x", "not a Z440")
    rows = db.execute(
        "SELECT listing_id, reason FROM rejects WHERE bargain_search_id=?", (sid,)
    ).fetchall()
    assert rows == [("x", "not a Z440")]


def test_reject_deletes_listing_observations_under_mapped_identity(db):
    pid = seed_identity(db)
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    seed_obs(db, "x", pid)
    seed_obs(db, "x", pid, price=90.0, day="2026-10-02")
    other = seed_identity(db, "Other thing")
    seed_obs(db, "x", other)
    enhanced.reject_listing(db, sid, "x", "wrong model")
    remaining = db.execute(
        "SELECT product_identity_id FROM price_observations"
    ).fetchall()
    assert remaining == [(other,)]  # only the mapped identity's rows are gone


def test_reject_appends_exclusions_block(db):
    pid = seed_identity(db, "HP Z440 workstation")
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    enhanced.reject_listing(db, sid, "x", "no monitors")
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (pid,)
    ).fetchone()[0]
    assert desc == "HP Z440 workstation\n\nExclusions:\nno monitors"


def test_reject_appends_to_existing_exclusions_block(db):
    pid = seed_identity(db, "HP Z440 workstation\n\nExclusions:\nfirst reason")
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    enhanced.reject_listing(db, sid, "x", "second reason")
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (pid,)
    ).fetchone()[0]
    assert desc == "HP Z440 workstation\n\nExclusions:\nfirst reason\nsecond reason"


def test_reject_dedupes_exclusion_by_casefold(db):
    pid = seed_identity(db, "HP Z440 workstation\n\nExclusions:\nNo Monitors")
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    enhanced.reject_listing(db, sid, "x", "no monitors")
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (pid,)
    ).fetchone()[0]
    assert desc.count("Monitors") == 1
    assert desc == "HP Z440 workstation\n\nExclusions:\nNo Monitors"


def test_duplicate_reject_same_search_and_listing_inserts_once(db):
    pid = seed_identity(db)
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    enhanced.reject_listing(db, sid, "x", "first reason")
    enhanced.reject_listing(db, sid, "x", "second reason")
    n = db.execute(
        "SELECT COUNT(*) FROM rejects WHERE bargain_search_id=?", (sid,)
    ).fetchone()[0]
    assert n == 1


def test_reject_unmapped_search_still_records_rejection(db):
    """No mapped identity: the identity correction is a no-op, the reject
    row and the search-level exclusion still land."""
    seed_listing(db, "x")
    sid = seed_search(db, None)
    enhanced.reject_listing(db, sid, "x", "nope")
    assert db.execute(
        "SELECT COUNT(*) FROM rejects WHERE bargain_search_id=?", (sid,)
    ).fetchone()[0] == 1
    excl = db.execute(
        "SELECT exclusions FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert json.loads(excl) == ["nope"]


# --- restore: reverses all three ---------------------------------------------


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


def test_restore_drops_reject_and_exclusion_line(site, db):
    pid = seed_identity(db, "HP Z440 workstation")
    seed_listing(db, "x", identity_id=pid)
    sid = seed_search(db, pid)
    call("POST", f"{site}/api/v1/searches/{sid}/rejections",
        {"listing_id": "x", "reason": "no monitors"})
    status, _ = call(
        "DELETE", f"{site}/api/v1/searches/{sid}/rejections/x"
    )
    assert status == 200
    assert db.execute("SELECT COUNT(*) FROM rejects").fetchone()[0] == 0
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (pid,)
    ).fetchone()[0]
    assert desc == "HP Z440 workstation"


def test_restore_rerecords_price_observation(site, db):
    pid = seed_identity(db, "HP Z440 workstation")
    seed_listing(db, "x", price=123.0, identity_id=pid)
    sid = seed_search(db, pid)
    seed_obs(db, "x", pid)
    call("POST", f"{site}/api/v1/searches/{sid}/rejections",
        {"listing_id": "x", "reason": "wrong"})
    assert db.execute(
        "SELECT COUNT(*) FROM price_observations"
    ).fetchone()[0] == 0
    call("DELETE", f"{site}/api/v1/searches/{sid}/rejections/x")
    rows = db.execute(
        "SELECT product_identity_id, condition, effective_price FROM price_observations"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pid
    assert rows[0][1] == "complete"
    assert rows[0][2] == 123.0


def test_restore_missing_rejection_404(site, db):
    pid = seed_identity(db)
    seed_listing(db, "zz")
    sid = seed_search(db, pid)
    status, body = call("DELETE", f"{site}/api/v1/searches/{sid}/rejections/zz")
    assert status == 404
    assert body["error"]["code"] == "rejection_not_found"
