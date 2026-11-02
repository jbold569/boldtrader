"""Ticket #68 — evidence gate on the automatic identity retune.

The retune that rides every search completion must stop firing when the
pass brought no new matched listings. Seam: src/identity.update_identity_from_search
against a temp DB with a fake router. First-ever synthesis and the explicit
human-triggered POST retune are ungated. Skip and failure both leave a
`retune_note` on the search for the daily digest.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.db import init_db
from src import identity as ident


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "gate.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def seed_identity(conn, description="a workstation", synthesized_at=None, matched_evidence=None):
    cur = conn.execute(
        "INSERT INTO product_identities (description, synthesized_at, matched_evidence) "
        "VALUES (?, ?, ?)",
        (description, synthesized_at, json.dumps(matched_evidence or [])),
    )
    conn.commit()
    return cur.lastrowid


def seed_search(conn, identity_id=None, status="complete", listing_ids=None):
    cur = conn.execute(
        "INSERT INTO bargain_searches "
        "(summary, product_identity, status, queries, product_identity_id, listing_ids) "
        "VALUES ('find a workstation', 'a workstation', ?, ?, ?, ?)",
        (status, json.dumps(["workstation"]), identity_id, json.dumps(listing_ids or {})),
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid, title="Dell Optiplex 7080"):
    raw = {
        "id": lid,
        "title": title,
        "price": 300.0,
        "condition": "used",
        "snippet": "clean machine",
        "marketplace": "offerup",
    }
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, ?)", (lid, json.dumps(raw)))


class Recorder:
    """Fake synthesize_description: records its inputs, returns a canned reply."""

    def __init__(self, reply="A refined prose identity."):
        self.reply = reply
        self.calls = []

    def __call__(self, evidence, model=None):
        self.calls.append(evidence)
        return self.reply


# --- gate closed: no new matched evidence -------------------------------------


def test_completion_without_new_matched_listings_skips(db, monkeypatch):
    iid = seed_identity(
        db,
        description="old description",
        synthesized_at="2026-10-01 00:00:00",
        matched_evidence=["a"],
    )
    seed_listing(db, "a")
    rec = Recorder()
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    sid = seed_search(db, iid, listing_ids={"a": "match"})

    ident.update_identity_from_search(db, sid)

    assert rec.calls == []  # no model call
    desc, syn = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert desc == "old description"  # byte-identical
    assert syn == "2026-10-01 00:00:00"  # untouched
    note = db.execute(
        "SELECT retune_note FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert note == "skipped: no new evidence"


def test_zero_match_completion_records_skip(db, monkeypatch):
    iid = seed_identity(
        db,
        description="old description",
        synthesized_at="2026-10-01 00:00:00",
        matched_evidence=["a"],
    )
    seed_listing(db, "a")
    rec = Recorder()
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    sid = seed_search(db, iid, listing_ids={"a": "not_match"})

    ident.update_identity_from_search(db, sid)

    assert rec.calls == []
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert desc == "old description"
    note = db.execute(
        "SELECT retune_note FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert note == "skipped: no new evidence"


# --- gate open: new matched evidence ------------------------------------------


def test_new_matched_listing_triggers_retune(db, monkeypatch):
    iid = seed_identity(
        db,
        description="old description",
        synthesized_at="2026-10-01 00:00:00",
        matched_evidence=["a"],
    )
    seed_listing(db, "a")
    seed_listing(db, "b", title="New arrival")
    rec = Recorder(reply="Retuned description.")
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    sid = seed_search(db, iid, listing_ids={"a": "match", "b": "match"})

    ident.update_identity_from_search(db, sid)

    assert len(rec.calls) == 1
    assert rec.calls[0]["mode"] == "retune"
    desc, syn = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert desc == "Retuned description."
    assert syn != "2026-10-01 00:00:00"
    baseline = db.execute(
        "SELECT matched_evidence FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert set(json.loads(baseline)) == {"a", "b"}
    note = db.execute(
        "SELECT retune_note FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert note is None


# --- first synthesis unchanged -------------------------------------------------


def test_first_synthesis_runs_and_records_baseline(db, monkeypatch):
    iid = seed_identity(db, description="a workstation")  # synthesized_at NULL
    seed_listing(db, "a")
    rec = Recorder(reply="Dell Optiplex 7080.")
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    sid = seed_search(db, iid, status="enriching", listing_ids={"a": "match"})

    ident.update_identity_from_search(db, sid)

    assert len(rec.calls) == 1
    assert rec.calls[0]["mode"] == "synthesize"
    desc, syn = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert desc == "Dell Optiplex 7080."
    assert syn is not None
    baseline = db.execute(
        "SELECT matched_evidence FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert set(json.loads(baseline)) == {"a"}


def test_first_completion_with_zero_matches_is_noop(db, monkeypatch):
    iid = seed_identity(db, description="a workstation")  # never synthesized
    seed_listing(db, "a")
    rec = Recorder()
    monkeypatch.setattr(ident.router, "synthesize_description", rec)
    sid = seed_search(db, iid, listing_ids={"a": "not_match"})

    ident.update_identity_from_search(db, sid)

    assert rec.calls == []
    desc, syn = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert (desc, syn) == ("a workstation", None)


# --- retune failure -----------------------------------------------------------


def test_retune_failure_keeps_description_and_records_failure(db, monkeypatch):
    iid = seed_identity(
        db,
        description="old description",
        synthesized_at="2026-10-01 00:00:00",
        matched_evidence=["a"],
    )
    seed_listing(db, "a")
    seed_listing(db, "b", title="New arrival")

    def boom(evidence, model=None):
        raise RuntimeError("router down")

    monkeypatch.setattr(ident.router, "synthesize_description", boom)
    sid = seed_search(db, iid, listing_ids={"a": "match", "b": "match"})

    ident.update_identity_from_search(db, sid)  # must not raise

    desc, syn = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert desc == "old description"
    assert syn == "2026-10-01 00:00:00"
    note = db.execute(
        "SELECT retune_note FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert note == "retune failed"


# --- explicit human retune is ungated ------------------------------------------


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "gate-api.db"
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


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


def test_explicit_retune_runs_without_new_evidence(site, db, monkeypatch):
    """Everything already in the baseline: the automatic path would skip,
    but the human-triggered retune always runs."""
    iid = seed_identity(
        db,
        description="old description",
        synthesized_at="2026-10-01 00:00:00",
        matched_evidence=["m"],
    )
    seed_listing(db, "m")
    seed_search(db, iid, listing_ids={"m": "match"})
    rec = Recorder(reply="Human-triggered rewrite.")
    monkeypatch.setattr("src.router.synthesize_description", rec)

    status, body = call("POST", f"{site}/api/v1/product-identities/{iid}/retune")

    assert status == 200
    assert len(rec.calls) == 1
    assert rec.calls[0]["mode"] == "retune"
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert desc == "Human-triggered rewrite."
    # the explicit retune's evidence becomes the gate baseline
    baseline = db.execute(
        "SELECT matched_evidence FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert set(json.loads(baseline)) == {"m"}


# --- migration -----------------------------------------------------------------


def test_old_db_gains_gate_columns(tmp_path, monkeypatch):
    path = tmp_path / "old-gate.db"
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
    seed.commit()
    seed.close()

    conn = init_db(path)

    bs_cols = {r[1] for r in conn.execute("PRAGMA table_info(bargain_searches)")}
    assert "retune_note" in bs_cols
    pi_cols = {r[1] for r in conn.execute("PRAGMA table_info(product_identities)")}
    assert "matched_evidence" in pi_cols
    assert (
        conn.execute(
            "SELECT matched_evidence FROM product_identities LIMIT 1"
        ).fetchone()
        is None
    )
    conn.close()
