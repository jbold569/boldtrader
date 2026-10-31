"""Re-resolution as an invokable action (ticket #61).

POST /api/v1/identities/reresolve runs the existing resolution step over
stored listing text (no marketplace refetch) with the full identity list
as candidates, and re-points listings whose resolution changed. Corrected
enrichments are skipped: the user's word beats the model.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import router
from src.db import init_db


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "rr.db"
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
    conn = sqlite3.connect(str(tmp_path / "rr.db"))
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


def seed_identity(conn, description):
    cur = conn.execute(
        "INSERT INTO product_identities (description) VALUES (?)", (description,)
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid, title="some title", snippet="some snippet",
                identity_id=None, price=100.0):
    raw = {
        "id": lid,
        "title": title,
        "snippet": snippet,
        "price": price,
        "marketplace": "offerup",
        "url": f"https://example.invalid/{lid}",
    }
    conn.execute(
        "INSERT INTO listings (id, raw, product_identity_id) VALUES (?, ?, ?)",
        (lid, json.dumps(raw), identity_id),
    )
    conn.commit()


def seed_enriched(conn, lid, product_desc="old desc", status="enriched",
                 corrected=0, condition="complete"):
    product = {
        "description": product_desc,
        "action": "match",
        "matched_id": 1,
        "confidence": "high",
    }
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, bundle, "
        "confidence, status, corrected) VALUES (?, ?, ?, '[]', 'high', ?, ?)",
        (lid, json.dumps(product), condition, status, corrected),
    )
    conn.commit()


def seed_obs(conn, lid, pid, day="2026-10-01"):
    conn.execute(
        "INSERT INTO price_observations "
        "(listing_id, product_identity_id, condition, effective_price, observed_at) "
        "VALUES (?, ?, 'complete', 100.0, ?)",
        (lid, pid, day),
    )
    conn.commit()


def resolver(**mapping):
    """Fake router.enrich: returns a 'match' product for the listing text.

    The listing text is the key; the value is (identity_id, description).
    An unknown listing text resolves 'unknown' (no identity).
    """

    def fake(text, candidates=None, authored="", model=None):
        hit = mapping.get(text)
        if hit is None:
            return {
                "product": {"description": "", "action": "unknown",
                           "matched_id": None, "confidence": "low"},
                "condition": "complete",
                "bundle": [],
            }
        pid, desc = hit
        return {
            "product": {"description": desc, "action": "match",
                       "matched_id": pid, "confidence": "high"},
            "condition": "complete",
            "bundle": [],
        }

    return fake


RERESOLVE_KEYS = {"moves", "total", "moved", "unchanged", "skipped_corrected"}


def test_reresolve_all_repoints_changed_listings(site, db, monkeypatch):
    old = seed_identity(db, "old wrong description")
    new = seed_identity(db, "Dell OptiPlex 7080 i5-10500")
    seed_listing(db, "a", title="Dell OptiPlex 7080", snippet="i5-10500",
                identity_id=old)
    seed_enriched(db, "a", product_desc="old wrong description")
    seed_obs(db, "a", old)
    monkeypatch.setattr(
        router, "enrich",
        resolver(**{"Dell OptiPlex 7080\n\ni5-10500": (new, "Dell OptiPlex 7080 i5-10500")}),
    )

    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"scope": "all"})
    assert status == 200
    assert set(body) == RERESOLVE_KEYS
    assert body["total"] == 1
    assert body["moved"] == 1
    assert body["moves"] == [
        {"listing_id": "a", "old_identity_id": old, "new_identity_id": new}
    ]
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='a'"
    ).fetchone() == (new,)
    # The listing's historical observations follow it to the new identity.
    assert db.execute(
        "SELECT DISTINCT product_identity_id FROM price_observations "
        "WHERE listing_id='a'"
    ).fetchall() == [(new,)]


def test_reresolve_skips_corrected(site, db, monkeypatch):
    old = seed_identity(db, "old")
    seed_listing(db, "c", title="t", snippet="s", identity_id=old)
    seed_enriched(db, "c", corrected=1)
    monkeypatch.setattr(router, "enrich", resolver(**{"t\n\ns": (99, "x")}))

    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"scope": "all"})
    assert status == 200
    assert body["skipped_corrected"] == 1
    assert body["moved"] == 0
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='c'"
    ).fetchone() == (old,)


def test_reresolve_targeted_listing_ids(site, db, monkeypatch):
    old = seed_identity(db, "old")
    new = seed_identity(db, "new thing")
    seed_listing(db, "a", title="t a", snippet="s a", identity_id=old)
    seed_enriched(db, "a", product_desc="old")
    seed_listing(db, "b", title="t b", snippet="s b", identity_id=old)
    seed_enriched(db, "b", product_desc="old")
    monkeypatch.setattr(
        router, "enrich", resolver(**{"t a\n\ns a": (new, "new thing")})
    )

    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"listing_ids": ["a"]})
    assert status == 200
    assert body["total"] == 1
    assert body["moved"] == 1
    # 'b' untouched: not targeted.
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='b'"
    ).fetchone() == (old,)


def test_reresolve_unchanged_resolution_is_not_a_move(site, db, monkeypatch):
    pid = seed_identity(db, "same thing")
    seed_listing(db, "a", title="t", snippet="s", identity_id=pid)
    seed_enriched(db, "a", product_desc="same thing")
    monkeypatch.setattr(router, "enrich", resolver(**{"t\n\ns": (pid, "same thing")}))

    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"scope": "all"})
    assert body["moved"] == 0
    assert body["unchanged"] == 1
    assert body["moves"] == []


def test_reresolve_unknown_resolution_leaves_listing(site, db, monkeypatch):
    pid = seed_identity(db, "something")
    seed_listing(db, "a", title="t", snippet="s", identity_id=pid)
    seed_enriched(db, "a", product_desc="something")
    monkeypatch.setattr(router, "enrich", resolver())  # everything unknown

    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"scope": "all"})
    assert body["moved"] == 0
    assert body["unchanged"] == 1
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='a'"
    ).fetchone() == (pid,)


def test_reresolve_sees_beyond_twenty_identities(site, db, monkeypatch):
    """The old fan-out candidate query capped at 20; a listing whose match
    is identity #25 must resolve it instead of failing candidate-blind."""
    for i in range(25):
        seed_identity(db, f"filler {i}")
    target = seed_identity(db, "the real match")  # id 26
    old = seed_identity(db, "old wrong",)
    seed_listing(db, "a", title="real", snippet="match here", identity_id=old)
    seed_enriched(db, "a", product_desc="old wrong")

    seen = {}

    def fake(text, candidates=None, authored="", model=None):
        seen["count"] = len(candidates)
        return {
            "product": {"description": "the real match", "action": "match",
                       "matched_id": target, "confidence": "high"},
            "condition": "complete",
            "bundle": [],
        }

    monkeypatch.setattr(router, "enrich", fake)
    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"scope": "all"})
    assert status == 200
    assert seen["count"] == 27
    assert body["moved"] == 1


def test_reresolve_bad_body_422(site):
    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"scope": "everything"})
    assert status == 422
    assert body["error"]["code"] == "invalid_reresolve"


def test_reresolve_unknown_listing_id_422(site, db):
    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"listing_ids": ["nope"]})
    assert status == 422
    assert body["error"]["code"] == "invalid_reresolve"
