"""Ticket #69 — stale-verdict accumulation across sweep rewrites.

Every Product Identity description rewrite adds its matched set to the
night's running stale union, held in its own table, immune to the
per-search stale_lids reset each fan-out performs. Listings carrying a
Correction are filtered out at read. The union feeds the existing
reresolve-by-ids path end-to-end.
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
from src import identity as ident
from src import stale


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "union.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "union.db"
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


def seed_identity(conn, description="a workstation", synthesized_at=None,
                 matched_evidence=None):
    cur = conn.execute(
        "INSERT INTO product_identities (description, synthesized_at, matched_evidence) "
        "VALUES (?, ?, ?)",
        (description, synthesized_at, json.dumps(matched_evidence or [])),
    )
    conn.commit()
    return cur.lastrowid


def seed_search(conn, identity_id=None, listing_ids=None):
    cur = conn.execute(
        "INSERT INTO bargain_searches "
        "(summary, product_identity, status, queries, product_identity_id, listing_ids) "
        "VALUES ('find a workstation', 'a workstation', 'enriching', ?, ?, ?)",
        (json.dumps(["workstation"]), identity_id, json.dumps(listing_ids or {})),
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid, title="Dell Optiplex 7080", snippet="clean machine",
                identity_id=None):
    raw = {
        "id": lid,
        "title": title,
        "snippet": snippet,
        "price": 300.0,
        "marketplace": "offerup",
        "url": f"https://example.invalid/{lid}",
    }
    conn.execute(
        "INSERT INTO listings (id, raw, product_identity_id) VALUES (?, ?, ?)",
        (lid, json.dumps(raw), identity_id),
    )
    conn.commit()


def seed_enriched(conn, lid, product_desc="old wrong description", corrected=0):
    product = {"description": product_desc, "action": "match",
               "matched_id": 1, "confidence": "high"}
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, bundle, "
        "confidence, status, corrected) VALUES (?, ?, 'complete', '[]', 'high', "
        "'enriched', ?)",
        (lid, json.dumps(product), corrected),
    )
    conn.commit()


class Rewriter:
    """Fake synthesize_description: a different reply each call so no
    rewrite is ever skipped for being unchanged."""

    def __init__(self):
        self.calls = 0

    def __call__(self, evidence, model=None):
        self.calls += 1
        return f"Rewrite {self.calls}."


# --- accumulation across rewrites --------------------------------------------


def test_union_accumulates_across_two_rewrites(db, monkeypatch):
    iid = seed_identity(
        db, description="old description",
        synthesized_at="2026-10-01 00:00:00", matched_evidence=["a"],
    )
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    monkeypatch.setattr(ident.router, "synthesize_description", Rewriter())

    sid1 = seed_search(db, iid, listing_ids={"a": "match", "b": "match"})
    ident.update_identity_from_search(db, sid1)
    assert stale.read_stale_union(db) == {"a", "b"}

    sid2 = seed_search(db, iid, listing_ids={"b": "match", "c": "unsure"})
    ident.update_identity_from_search(db, sid2)
    assert stale.read_stale_union(db) == {"a", "b", "c"}


def test_union_survives_fanout_reset(db, monkeypatch):
    """The per-search stale_lids wipe (fan_out start) must not touch the
    union: that reset is exactly the bug this accumulator sidesteps."""
    iid = seed_identity(
        db, description="old description",
        synthesized_at="2026-10-01 00:00:00", matched_evidence=[],
    )
    for lid in ("a", "b"):
        seed_listing(db, lid)
    monkeypatch.setattr(ident.router, "synthesize_description", Rewriter())

    sid1 = seed_search(db, iid, listing_ids={"a": "match", "b": "match"})
    ident.update_identity_from_search(db, sid1)
    assert stale.read_stale_union(db) == {"a", "b"}

    # Simulate the next search's fan-out wiping its per-search column.
    db.execute("UPDATE bargain_searches SET stale_lids='[]' WHERE id=?", (sid1,))
    db.commit()
    assert stale.read_stale_union(db) == {"a", "b"}


def test_duplicate_lids_collapse(db, monkeypatch):
    """Same lids replayed through a second rewrite add nothing: the
    union's PRIMARY KEY collapses duplicates."""
    iid = seed_identity(
        db, description="old description",
        synthesized_at="2026-10-01 00:00:00", matched_evidence=[],
    )
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    monkeypatch.setattr(ident.router, "synthesize_description", Rewriter())

    sid1 = seed_search(db, iid, listing_ids={"a": "match", "b": "match"})
    ident.update_identity_from_search(db, sid1)
    # Same two lids plus one new one so the #68 gate lets it rewrite.
    sid2 = seed_search(db, iid, listing_ids={"a": "match", "b": "unsure", "c": "match"})
    ident.update_identity_from_search(db, sid2)

    assert stale.read_stale_union(db) == {"a", "b", "c"}
    assert db.execute("SELECT COUNT(*) FROM stale_union").fetchone()[0] == 3


# --- corrected filtering ------------------------------------------------------


def test_corrected_listings_filtered_at_construction(db, monkeypatch):
    """A Correction recorded after the stale mark still stays out of the
    union: the filter runs at construction, not at append time."""
    iid = seed_identity(
        db, description="old description",
        synthesized_at="2026-10-01 00:00:00", matched_evidence=[],
    )
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    monkeypatch.setattr(ident.router, "synthesize_description", Rewriter())

    sid = seed_search(db, iid, listing_ids={"a": "match", "b": "match", "c": "match"})
    ident.update_identity_from_search(db, sid)
    assert stale.read_stale_union(db) == {"a", "b", "c"}

    seed_enriched(db, "b", corrected=1)
    assert stale.read_stale_union(db) == {"a", "c"}


# --- empty night --------------------------------------------------------------


def test_empty_night_yields_empty_union(db):
    """No rewrites -> nothing accumulates -> the union starts and stays empty."""
    assert stale.read_stale_union(db) == set()


# --- handoff into reresolve-by-ids ---------------------------------------------


def resolver(**mapping):
    """Fake router.enrich: maps listing text to (identity_id, description)."""

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


def test_union_feeds_reresolve_by_ids(site, db, monkeypatch):
    """End-to-end: a rewrite builds the union, a Correction drops one
    lid from it, and the union drives the reresolve-by-ids path to
    correct re-verdicts on the rest."""
    old = seed_identity(
        db, description="old wrong description",
        synthesized_at="2026-10-01 00:00:00", matched_evidence=["a"],
    )
    new = seed_identity(db, "Dell OptiPlex 7080 i5-10500")
    seed_listing(db, "a", title="Dell Optiplex 7080", snippet="i5-10500",
                identity_id=old)
    seed_listing(db, "b", title="Lenovo ThinkCentre", snippet="i7 junk",
                identity_id=old)
    seed_enriched(db, "a")
    seed_enriched(db, "b")
    monkeypatch.setattr(ident.router, "synthesize_description", Rewriter())

    sid = seed_search(db, old, listing_ids={"a": "match", "b": "unsure"})
    ident.update_identity_from_search(db, sid)
    assert stale.read_stale_union(db) == {"a", "b"}

    # 'a' gets a Correction: user truth, stays out of the union.
    db.execute(
        "UPDATE enrichments SET corrected=1, product=? WHERE listing_id=?",
        (json.dumps({"description": "corrected by hand", "action": "match",
                    "matched_id": old, "confidence": "high"}), "a"),
    )
    db.commit()
    union = stale.read_stale_union(db)
    assert union == {"b"}

    monkeypatch.setattr(
        "src.router.enrich",
        resolver(**{"Lenovo ThinkCentre\n\ni7 junk": (new, "Dell OptiPlex 7080 i5-10500")}),
    )

    status, body = call("POST", f"{site}/api/v1/identities/reresolve",
                       {"listing_ids": sorted(union)})
    assert status == 200
    assert body["total"] == 1
    assert body["moved"] == 1
    assert body["moves"] == [
        {"listing_id": "b", "old_identity_id": old, "new_identity_id": new}
    ]
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='b'"
    ).fetchone() == (new,)
    # The corrected listing was never touched by the handoff.
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='a'"
    ).fetchone() == (old,)
