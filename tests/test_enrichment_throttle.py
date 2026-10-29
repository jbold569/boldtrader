"""Throttle tests for the enrichment worker (fanout).

A dead network makes fetch_detail fail in ~300ms; an unpaced drain of
hundreds of rows then becomes a request firehose. These tests fake the
clock (no real waiting) and assert the worker paces every row and cools
down on a burst of consecutive failures.
"""

from __future__ import annotations

import json

import pytest

from src import fanout
from src.db import init_db
from src.marketplace import ListingDetail


class Boom(Exception):
    pass


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


class GoodMP:
    def fetch_detail(self, listing):
        return ListingDetail(description="a fine widget")


class DeadMP:
    def fetch_detail(self, listing):
        raise Boom("name or service not known")


def good_enrich(text, authored=""):
    return {
        "product": {"name": "widget"},
        "condition": "good",
        "bundle": ["power cord"],
        "confidence": 0.9,
    }


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def seed_pending(conn, lid):
    raw = json.dumps(
        {
            "id": lid.split(":", 1)[1],
            "title": "Dell Optiplex",
            "price": 50.0,
            "condition": "used",
            "snippet": "works",
            "marketplace": "test",
        }
    )
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, ?)", (lid, raw))
    conn.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES (?, 'pending')", (lid,)
    )
    conn.commit()



def test_worker_paces_between_rows(db, monkeypatch):
    for i in range(3):
        seed_pending(db, f"test:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    def fake_sleep(s):
        # first idle poll after the drain: stop the never-ending worker
        if s == 2.0 and all(
            r[0] == 3
            for r in db.execute(
                "SELECT COUNT(*) FROM enrichments WHERE status='enriched'"
            )
        ):
            raise StopIteration
        clock.sleep(s)

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": GoodMP()}, poll_seconds=2.0)

    assert clock.sleeps[:2] == [
        fanout.ENRICH_MIN_INTERVAL_SECONDS,
        fanout.ENRICH_MIN_INTERVAL_SECONDS,
    ]
    n = db.execute("SELECT COUNT(*) FROM enrichments WHERE status='enriched'").fetchone()[0]
    assert n == 3


def test_consecutive_failures_trigger_cooldown(db, monkeypatch):
    n_rows = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    for i in range(n_rows):
        seed_pending(db, f"test:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    def fake_sleep(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": DeadMP()}, poll_seconds=2.0)

    assert fanout.ENRICH_COOLDOWN_SECONDS in clock.sleeps
    n = db.execute("SELECT COUNT(*) FROM enrichments WHERE status='failed'").fetchone()[0]
    assert n == n_rows


def test_single_failure_does_not_cool_down(db, monkeypatch):
    """One bad listing among good ones must not stall the queue for 5 minutes."""
    for i in range(3):
        seed_pending(db, f"test:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    calls = {"n": 0}

    class MostlyGood:
        def fetch_detail(self, listing):
            calls["n"] += 1
            if calls["n"] == 2:
                raise Boom("bad listing")
            return ListingDetail(description="fine")

    def fake_sleep(s):
        if s == 2.0:  # idle poll: everything processed
            raise StopIteration
        clock.sleep(s)

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": MostlyGood()}, poll_seconds=2.0)

    assert fanout.ENRICH_COOLDOWN_SECONDS not in clock.sleeps
