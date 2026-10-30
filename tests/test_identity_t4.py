"""T4 — Identity synthesis and retuning (ticket #55, ADR 0012).

Seam: src/identity.py against a temp DB with a fake router. Covers the
seed-on-create link, the first-completion synthesis, the retune on
subsequent completion (rejects, authored descriptions, threshold
edits), the stale-verdict flag that rides every description change, the
sift consuming the description instead of the seed phrase, and the
SQLite migrations for the new columns.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request

import pytest

import src.identity as ident
import src.router as router_mod
from src.db import init_db
from src.marketplace import Listing, SearchResult


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t4.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def seed_identity(conn, description="seed phrase", deal_threshold=None, synthesized_at=None):
    cur = conn.execute(
        "INSERT INTO product_identities (description, deal_threshold, synthesized_at) "
        "VALUES (?, ?, ?)",
        (description, deal_threshold, synthesized_at),
    )
    conn.commit()
    return cur.lastrowid


def seed_search(conn, identity_id=None, status="enriching", listing_ids=None):
    cur = conn.execute(
        "INSERT INTO bargain_searches "
        "(summary, product_identity, status, queries, product_identity_id, listing_ids) "
        "VALUES ('find a workstation', 'a workstation', ?, ?, ?, ?)",
        (status, json.dumps(["workstation"]), identity_id, json.dumps(listing_ids or {})),
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid, title="Dell Optiplex 7080", authored=None):
    raw = {
        "id": lid,
        "title": title,
        "price": 300.0,
        "condition": "used",
        "snippet": "clean machine",
        "marketplace": "offerup",
    }
    conn.execute(
        "INSERT INTO listings (id, raw, authored_description) VALUES (?, ?, ?)",
        (lid, json.dumps(raw), authored),
    )


def seed_enrichment(conn, lid, product_desc="Dell Optiplex 7080", status="enriched"):
    product = {"description": product_desc, "action": "mint", "matched_id": None}
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, bundle, confidence, status) "
        "VALUES (?, ?, 'complete', '[]', 'high', ?)",
        (lid, json.dumps(product), status),
    )


class Recorder:
    """Fake synthesize_description: records its inputs, returns a canned reply."""

    def __init__(self, reply="A refined prose identity."):
        self.reply = reply
        self.calls = []

    def __call__(self, evidence):
        self.calls.append(evidence)
        return self.reply


# --- seed --------------------------------------------------------------------


def test_create_search_seeds_identity(db):
    from src import chat

    draft = {
        "summary": "Used Dell workstations under $300",
        "product_identity": "Dell Optiplex workstation",
        "queries": ["dell optiplex"],
        "exclusions": [],
        "target_price": 300.0,
        "location": "Kenmore, WA",
    }

    sid = chat.create_search(db, draft)

    row = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] is not None
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (row[0],)
    ).fetchone()[0]
    assert desc == "Dell Optiplex workstation"
    assert db.execute(
        "SELECT synthesized_at FROM product_identities WHERE id=?", (row[0],)
    ).fetchone()[0] is None  # a seed is not a synthesis


# --- collection --------------------------------------------------------------


def test_collect_matched_context_skips_rejects(db):
    iid = seed_identity(db)
    seed_listing(db, "a", title="Dell Optiplex 7080")
    seed_listing(db, "b", title="some monitor", authored="not this")
    seed_listing(db, "c", title="Dell Optiplex 9020")
    seed_enrichment(db, "a", product_desc="Dell Optiplex 7080 i5")
    seed_enrichment(db, "c", product_desc="Dell Optiplex 9020 i7", status="failed")
    sid = seed_search(
        db,
        iid,
        listing_ids={"a": "match", "b": "not_match", "c": "unsure"},
    )
    db.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, 'c', 'too loud')",
        (sid,),
    )
    db.commit()

    ctx = ident.collect_matched_context(db, sid)

    assert ctx == [
        {"title": "Dell Optiplex 7080", "product": "Dell Optiplex 7080 i5", "authored": None},
    ]


# --- first synthesis ---------------------------------------------------------


def test_first_completion_synthesizes(db, monkeypatch):
    iid = seed_identity(db, description="a workstation")
    seed_listing(db, "a", title="Dell Optiplex 7080")
    rec = Recorder(reply="Dell Optiplex 7080, i5-10500/16GB/512GB SSD")
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    sid = seed_search(db, iid, listing_ids={"a": "match"})

    ident.update_identity_from_search(db, sid)

    row = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row[0] == "Dell Optiplex 7080, i5-10500/16GB/512GB SSD"
    assert row[1] is not None
    assert rec.calls[0]["mode"] == "synthesize"
    assert rec.calls[0]["matched"] == [
        {"title": "Dell Optiplex 7080", "product": None, "authored": None}
    ]


def test_description_change_flags_verdicts_stale(db, monkeypatch):
    iid = seed_identity(db, description="a workstation")
    seed_listing(db, "a")
    seed_listing(db, "b")
    monkeypatch.setattr(
        ident.router, "synthesize_description", lambda ev: "Brand new description."
    )
    sid = seed_search(db, iid, listing_ids={"a": "match", "b": "unsure"})

    ident.update_identity_from_search(db, sid)

    stale = db.execute(
        "SELECT stale_lids FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert set(json.loads(stale)) == {"a", "b"}


def test_empty_description_is_rejected(db, monkeypatch):
    iid = seed_identity(db, description="a workstation")
    seed_listing(db, "a")
    monkeypatch.setattr(ident.router, "synthesize_description", lambda ev: "   ")
    sid = seed_search(db, iid, listing_ids={"a": "match"})

    ident.update_identity_from_search(db, sid)

    row = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row == ("a workstation", None)  # unchanged


def test_model_error_leaves_identity_untouched(db, monkeypatch):
    iid = seed_identity(db, description="a workstation")
    seed_listing(db, "a")

    def boom(evidence):
        raise router_mod.RouterError("router down")

    monkeypatch.setattr(ident.router, "synthesize_description", boom)
    sid = seed_search(db, iid, listing_ids={"a": "match"})

    ident.update_identity_from_search(db, sid)  # must not raise

    row = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row == ("a workstation", None)
    assert (
        db.execute("SELECT stale_lids FROM bargain_searches WHERE id=?", (sid,)).fetchone()[0]
        == "[]"
    )


def test_identical_replacement_does_not_flag_stale(db, monkeypatch):
    """A synthesis that repeats the current description changes nothing, so
    verdicts must not be flagged."""
    iid = seed_identity(db, description="same text")
    seed_listing(db, "a")
    monkeypatch.setattr(ident.router, "synthesize_description", lambda ev: "same text")
    sid = seed_search(db, iid, listing_ids={"a": "match"})

    ident.update_identity_from_search(db, sid)

    stale = db.execute(
        "SELECT stale_lids FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert json.loads(stale) == []


# --- retune ------------------------------------------------------------------


def test_retune_incorporates_evidence(db, monkeypatch):
    iid = seed_identity(
        db, description="old description", deal_threshold=18.0, synthesized_at="2026-10-01 00:00:00"
    )
    rec = Recorder(reply="Retuned description.")
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    seed_listing(db, "r", title="rejected thing", authored="wrong model entirely")
    seed_listing(db, "m", title="a match")
    sid = seed_search(
        db, iid, status="complete", listing_ids={"r": "not_match", "m": "match"}
    )
    db.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, 'r', 'different brand')",
        (sid,),
    )
    db.commit()

    ident.update_identity_from_search(db, sid)

    ev = rec.calls[0]
    assert ev["mode"] == "retune"
    assert ev["current_description"] == "old description"
    assert ev["rejects"] == [{"title": "rejected thing", "reason": "different brand"}]
    assert ev["authored_descriptions"] == ["wrong model entirely"]
    assert ev["deal_threshold"] == 18.0
    assert ev["matched"] == [
        {"title": "a match", "product": None, "authored": None}
    ]
    row = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row[0] == "Retuned description."
    assert row[1] != "2026-10-01 00:00:00"


def test_retune_pools_reject_reasons(db, monkeypatch):
    """The evidence pack carries the union of reasons, not one row per
    listing: two rejects with the same reason say 'too expensive' once."""
    iid = seed_identity(db, synthesized_at="2026-10-01 00:00:00")
    rec = Recorder(reply="Retuned.")
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    seed_listing(db, "r1", title="t1")
    seed_listing(db, "r2", title="t2")
    seed_listing(db, "x", title="matched one")
    sid = seed_search(db, iid, status="complete", listing_ids={"x": "match"})
    for lid in ("r1", "r2"):
        db.execute(
            "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, ?, 'too expensive')",
            (sid, lid),
        )
    db.commit()

    ident.update_identity_from_search(db, sid)

    assert rec.calls[0]["rejects"] == [{"title": "t1", "reason": "too expensive"}]


# --- router.synthesize_description -------------------------------------------


def test_router_synthesize_description_returns_prose(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["messages"] = json["messages"]

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "Dell Optiplex 7080, i5"}}]}

        return Resp()

    monkeypatch.setattr(router_mod.requests, "post", fake_post)

    out = router_mod.synthesize_description(
        {
            "mode": "synthesize",
            "current_description": "",
            "matched": [{"title": "Dell Optiplex 7080", "product": "i5/16GB", "authored": None}],
            "rejects": [],
            "authored_descriptions": [],
            "deal_threshold": 25.0,
        }
    )

    assert out == "Dell Optiplex 7080, i5"
    assert "Dell Optiplex 7080" in captured["messages"][1]["content"]


# --- sift consumes the description -------------------------------------------


class OneShotMP:
    name = "fake"

    def __init__(self, listings):
        self._listings = listings

    def search(self, query, page=1, location=None):
        return SearchResult(
            listings=self._listings,
            total_results=len(self._listings),
            page=1,
            page_size=50,
            total_pages=1,
        )


def test_sift_receives_identity_description(db, monkeypatch):
    from src import fanout

    seen = []

    def fake_sift(summary, product_identity, exclusions=None):
        seen.append(product_identity)
        return "not_match"

    monkeypatch.setattr(fanout.router, "sift", fake_sift)

    iid = seed_identity(db, description="Fresh prose identity", synthesized_at="2026-10-20 00:00:00")
    sid = seed_search(db, iid, status="active", listing_ids={})
    listings = [Listing(id=f"x{i}", title=f"title {i}", price=10.0) for i in range(3)]

    fanout.fan_out({"fake": OneShotMP(listings)}, sid, "Kenmore, WA")

    assert seen and all(s == "Fresh prose identity" for s in seen)


def test_sift_falls_back_to_seed_when_identity_unsynthesized(db, monkeypatch):
    from src import fanout

    seen = []

    def fake_sift(summary, product_identity, exclusions=None):
        seen.append(product_identity)
        return "not_match"

    monkeypatch.setattr(fanout.router, "sift", fake_sift)

    iid = seed_identity(db, description="a workstation")  # synthesized_at NULL
    sid = seed_search(db, iid, status="active", listing_ids={})
    listings = [Listing(id="x1", title="title", price=10.0)]

    fanout.fan_out({"fake": OneShotMP(listings)}, sid, "Kenmore, WA")

    assert seen and all(s == "a workstation" for s in seen)


# --- API card staleness ------------------------------------------------------

API = "/api/v1/searches"


def test_result_card_verdict_stale_flag(db):
    """verdict_stale tracks the search's stale_lids, per card."""
    import threading
    from http.server import ThreadingHTTPServer
    from src import server as server_mod

    server_mod.Handler.marketplaces = {}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "offerup"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        seed_listing(db, "offerup:1")
        seed_listing(db, "offerup:2")
        sid = seed_search(
            db, None, status="complete", listing_ids={"offerup:1": "match", "offerup:2": "match"}
        )
        db.execute(
            "UPDATE bargain_searches SET stale_lids=? WHERE id=?",
            (json.dumps(["offerup:1"]), sid),
        )
        db.commit()

        req = urllib.request.Request(f"{base}{API}/{sid}/results?verdict=all")
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())

        by_id = {c["listing_id"]: c for c in body["items"]}
        assert by_id["offerup:1"]["verdict_stale"] is True
        assert by_id["offerup:2"]["verdict_stale"] is False
    finally:
        httpd.shutdown()


# --- migrations --------------------------------------------------------------


def test_old_db_gains_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old2.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    seed = sqlite3.connect(path)
    seed.executescript(
        """
        CREATE TABLE bargain_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary TEXT NOT NULL,
            product_identity TEXT NOT NULL,
            target_price REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE listings (
            id TEXT PRIMARY KEY,
            raw TEXT NOT NULL,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    seed.execute("INSERT INTO bargain_searches (summary, product_identity) VALUES ('old', 'x')")
    seed.commit()
    seed.close()

    conn = init_db(path)

    bs_cols = {r[1] for r in conn.execute("PRAGMA table_info(bargain_searches)")}
    assert {"product_identity_id", "stale_lids"} <= bs_cols
    assert (
        conn.execute("SELECT stale_lids FROM bargain_searches WHERE id=1").fetchone()[0] == "[]"
    )
    pi_cols = {r[1] for r in conn.execute("PRAGMA table_info(product_identities)")}
    assert "synthesized_at" in pi_cols
    conn.close()
