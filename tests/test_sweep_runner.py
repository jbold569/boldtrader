"""Ticket #71 — sweep runner: the full daily A→B→C chain, persisted.

The chain: phase A re-fans every Bargain Search serially (each with a
~20-minute timeout, a raising search contained), phase B bulk-refreshes
live prices, phase C reresolves the night's accumulated stale union and
clears it. The whole run lands in sweep_runs: started, finished,
outcome, report. Fakes for everything: marketplaces, fan-out, price
refresh, clock (FakeClock pattern from test_enrichment_throttle).
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from src.db import init_db
from src import stale
from src import sweep


class FakeClock:
    """time.monotonic/sleep stand-in that records sleeps and advances virtual time."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "sweep.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def seed_search(conn, summary="find the widget"):
    cur = conn.execute(
        "INSERT INTO product_identities (description, synthesized_at, matched_evidence) "
        "VALUES ('seed words', NULL, '[]')"
    )
    pid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO bargain_searches "
        "(summary, product_identity, location, product_identity_id) "
        "VALUES (?, 'widget', 'Kenmore, WA', ?)",
        (summary, pid),
    )
    conn.commit()
    return cur.lastrowid, pid


def completing_fan(db_path, verdicts_by_search, rewritten_desc):
    """Fake fan_out: persists verdicts and their listing rows, then
    simulates the identity description rewrite that rides the
    search_complete transition. Opens its own connection: the sweep runs
    this in a watchdog thread."""

    def fan(marketplaces, search_id, location=None):
        conn = sqlite3.connect(str(db_path))
        try:
            verdicts = verdicts_by_search.get(search_id, {})
            for lid in verdicts:
                raw = json.dumps(
                    {
                        "id": lid.split(":", 1)[1],
                        "title": "widget",
                        "price": 100.0,
                        "snippet": "x",
                        "marketplace": lid.split(":", 1)[0],
                    }
                )
                conn.execute(
                    "INSERT OR IGNORE INTO listings (id, raw) VALUES (?, ?)", (lid, raw)
                )
            conn.execute(
                "UPDATE bargain_searches SET status='complete', listing_ids=? WHERE id=?",
                (json.dumps(verdicts), search_id),
            )
            pid = conn.execute(
                "SELECT product_identity_id FROM bargain_searches WHERE id=?", (search_id,)
            ).fetchone()[0]
            new_desc = rewritten_desc[str(search_id)]
            matched = [lid for lid, v in verdicts.items() if v in ("match", "unsure")]
            conn.execute(
                "UPDATE product_identities SET description=?, synthesized_at=?, matched_evidence=? "
                "WHERE id=?",
                (new_desc, "2026-11-01T13:00:00Z", json.dumps(matched), pid),
            )
            stale.record_stale(conn, matched)
            conn.commit()
        finally:
            conn.close()

    return fan


FAKE_B_REPORT = {
    "refreshed_count": 4,
    "failed_count": 1,
    "blocked_marketplaces": {},
    "price_drops": {"count": 2, "top_3": []},
    "started_at": "2026-11-01T06:00:00Z",
    "ended_at": "2026-11-01T06:30:00Z",
}


def fake_b(conn, marketplaces, clock=None):
    return dict(FAKE_B_REPORT)


def fake_reresolve(record):
    def reresolve(conn, listing_ids):
        record["ids"] = list(listing_ids)
        return {
            "moves": [{"listing_id": l} for l in listing_ids],
            "total": len(listing_ids),
            "moved": len(listing_ids),
            "unchanged": 0,
            "skipped_corrected": 0,
        }

    return reresolve


# --- happy path ---------------------------------------------------------------


def test_happy_path_full_chain(tmp_path, db, monkeypatch):
    s1, _ = seed_search(db, "search one")
    s2, _ = seed_search(db, "search two")
    v1 = {"ebay:1": "match", "ebay:2": "no", "ebay:3": "match"}
    v2 = {"offerup:a": "match", "offerup:b": "no"}
    monkeypatch.setattr(
        sweep, "fan_out",
        completing_fan(tmp_path / "sweep.db", {s1: v1, s2: v2},
                       {"1": "new words one", "2": "new words two"}),
    )
    monkeypatch.setattr(sweep, "bulk_refresh_price", fake_b)
    rr_calls: dict = {}
    monkeypatch.setattr(sweep, "reresolve_by_ids", fake_reresolve(rr_calls))

    report = sweep.run_sweep({}, db, clock=FakeClock())

    assert [s["search_id"] for s in report["searches"]] == [s1, s2]
    first, second = report["searches"]
    assert first["new_listing_count"] == 3
    assert first["match_count"] == 2
    assert first["failed"] is False
    assert first["timed_out"] is False
    assert second["new_listing_count"] == 2
    assert second["match_count"] == 1
    # Each description rewrite captured with old and new text + evidence count.
    assert first["old_desc"] == "seed words"
    assert first["new_desc"] == "new words one"
    assert first["evidence_count"] == 2
    assert second["old_desc"] == "seed words"
    assert second["new_desc"] == "new words two"
    # Phase B report carried through.
    assert report["price_refresh"]["refreshed_count"] == 4
    # Phase C consumed the accumulated union from BOTH searches.
    assert sorted(rr_calls["ids"]) == ["ebay:1", "ebay:3", "offerup:a"]
    # The union is cleared after the reresolve completes.
    assert db.execute("SELECT COUNT(*) FROM stale_union").fetchone()[0] == 0
    assert report["outcome"] == "complete"

    row = db.execute(
        "SELECT started_at, finished_at, outcome, report FROM sweep_runs"
    ).fetchall()
    assert len(row) == 1
    started_at, finished_at, outcome, report_json = row[0]
    assert outcome == "complete"
    assert started_at and finished_at
    assert json.loads(report_json) == report


# --- mid-chain failure --------------------------------------------------------


def test_raising_search_is_contained_and_recorded(tmp_path, db, monkeypatch):
    s1, _ = seed_search(db, "search one")
    s2, _ = seed_search(db, "search two")
    v1 = {"ebay:1": "match"}
    base_fan = completing_fan(tmp_path / "sweep.db", {s1: v1}, {"1": "rewritten"})

    def fan(marketplaces, search_id, location=None):
        if search_id == s2:
            raise RuntimeError("fan exploded")
        base_fan(marketplaces, search_id, location)

    monkeypatch.setattr(sweep, "fan_out", fan)
    monkeypatch.setattr(sweep, "bulk_refresh_price", fake_b)
    rr_calls: dict = {}
    monkeypatch.setattr(sweep, "reresolve_by_ids", fake_reresolve(rr_calls))

    report = sweep.run_sweep({}, db, clock=FakeClock())

    assert report["searches"][0]["failed"] is False
    assert report["searches"][1]["search_id"] == s2
    assert report["searches"][1]["failed"] is True
    assert "fan exploded" in report["searches"][1]["error"]
    # The chain continued past the failure: phase B and C both ran.
    assert report["price_refresh"]["refreshed_count"] == 4
    assert rr_calls["ids"] == ["ebay:1"]
    assert report["outcome"] == "partial"

    outcome, = db.execute(
        "SELECT outcome FROM sweep_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert outcome == "partial"


# --- timeout ------------------------------------------------------------------


def test_timeout_marks_search_and_chain_continues(tmp_path, db, monkeypatch):
    s1, _ = seed_search(db, "hung search")
    s2, _ = seed_search(db, "healthy search")
    release = threading.Event()  # never set: s1's fan-out never returns
    v2 = {"offerup:a": "match", "offerup:b": "match"}
    base_fan = completing_fan(tmp_path / "sweep.db", {s2: v2}, {"2": "rewritten two"})

    def fan(marketplaces, search_id, location=None):
        if search_id == s1:
            release.wait()
            return
        base_fan(marketplaces, search_id, location)

    monkeypatch.setattr(sweep, "fan_out", fan)
    monkeypatch.setattr(sweep, "bulk_refresh_price", fake_b)
    rr_calls: dict = {}
    monkeypatch.setattr(sweep, "reresolve_by_ids", fake_reresolve(rr_calls))

    clock = FakeClock()
    report = sweep.run_sweep({}, db, clock=clock)

    first = report["searches"][0]
    assert first["search_id"] == s1
    assert first["timed_out"] is True
    assert first["failed"] is True
    # The wait passed the ~20-minute cap on the injected clock.
    assert clock.now >= sweep.PER_SEARCH_TIMEOUT_SECONDS
    # Chain continued: the healthy search and the later phases ran.
    second = report["searches"][1]
    assert second["search_id"] == s2
    assert second["failed"] is False
    assert second["match_count"] == 2
    assert rr_calls["ids"] == ["offerup:a", "offerup:b"]
    assert report["outcome"] == "partial"


# --- empty board ---------------------------------------------------------------


def test_empty_board_is_a_valid_run(db, monkeypatch):
    monkeypatch.setattr(sweep, "bulk_refresh_price", fake_b)
    rr_calls: dict = {}
    monkeypatch.setattr(sweep, "reresolve_by_ids", fake_reresolve(rr_calls))

    report = sweep.run_sweep({}, db, clock=FakeClock())

    assert report["searches"] == []
    # Empty union: phase C does nothing but the run record is still written.
    assert rr_calls.get("ids") is None
    assert report["reresolve"]["total"] == 0
    assert report["outcome"] == "complete"
    row = db.execute(
        "SELECT started_at, finished_at, outcome FROM sweep_runs"
    ).fetchone()
    assert row is not None
    assert row[2] == "complete"
