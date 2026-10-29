"""Tests for manual Re-enrichment.

Seam: reenrich_search() core logic against a temp DB. The worker itself
is not started: re-queueing to 'pending' is the whole integration, and
the existing throttle tests cover the drain. The route-level tests that
used to live here hit the legacy /reenrich POST handler, deleted at the
M8 cutover (ticket #51); the JSON-API equivalent is
tests/test_api_results.py's POST .../reenrichment section.
"""

from __future__ import annotations

import json

import pytest

from src.db import init_db
from src.fanout import reenrich_search


def seed_listing(conn, lid, enrichment=None):
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, '{}')", (lid,))
    if enrichment is not None:
        conn.execute(
            "INSERT INTO enrichments (listing_id, status) VALUES (?, ?)",
            (lid, enrichment),
        )


def seed_search(conn, verdicts, status="complete"):
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status, listing_ids) "
        "VALUES ('test search', 'thing', ?, ?)",
        (status, json.dumps(verdicts)),
    )
    return cur.lastrowid


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


# --- core --------------------------------------------------------------------


def test_missing_and_failed_are_queued(db):
    seed_listing(db, "a")  # missing enrichment
    seed_listing(db, "b", "failed")
    seed_listing(db, "c", "enriched")  # must not be touched
    sid = seed_search(db, {"a": "match", "b": "unsure", "c": "match"})

    n = reenrich_search(db, sid)

    assert n == 2
    rows = dict(db.execute("SELECT listing_id, status FROM enrichments").fetchall())
    assert rows == {"a": "pending", "b": "pending", "c": "enriched"}
    st = db.execute(
        "SELECT status FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert st == "enriching"


def test_all_enriched_is_a_noop(db):
    seed_listing(db, "a", "enriched")
    sid = seed_search(db, {"a": "match"})

    n = reenrich_search(db, sid)

    assert n == 0
    st = db.execute(
        "SELECT status FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert st == "complete"


def test_not_match_verdicts_ignored(db):
    seed_listing(db, "a")
    # 'ghost' was never persisted as a listing; it must not be queued either.
    sid = seed_search(db, {"a": "match", "ghost": "not_match"})

    n = reenrich_search(db, sid)

    assert n == 1
    rows = db.execute("SELECT listing_id FROM enrichments").fetchall()
    assert [r[0] for r in rows] == ["a"]


def test_missing_search_returns_zero(db):
    assert reenrich_search(db, 999) == 0


def test_second_call_is_idempotent(db):
    seed_listing(db, "a")
    sid = seed_search(db, {"a": "match"})
    assert reenrich_search(db, sid) == 1
    assert reenrich_search(db, sid) == 0
