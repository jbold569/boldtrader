"""Throttle tests for the enrichment worker (fanout).

A dead network makes fetch_detail fail in ~300ms; an unpaced drain of
hundreds of rows then becomes a request firehose. These tests fake the
clock (no real waiting) and assert the worker paces every row and cools
down per marketplace (ticket #66, ADR 0015): a run of blocked responses
(403/429/503) escalates only that marketplace's cooldown, while other
marketplaces keep draining at normal pace.
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


def good_enrich(text, candidates=None, authored=""):
    return {
        "product": {
            "description": "Dell OptiPlex 3060",
            "action": "mint",
            "matched_id": None,
            "confidence": "high",
        },
        "condition": "complete",
        "bundle": [{"description": "power cord", "confidence": "high"}],
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
            "marketplace": lid.split(":", 1)[0],
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


def test_blocked_burst_triggers_cooldown(db, monkeypatch):
    n_rows = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    for i in range(n_rows):
        seed_pending(db, f"test:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class BlockedMP:
        def fetch_detail(self, listing):
            raise Blocked()

    def fake_sleep(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": BlockedMP()}, poll_seconds=2.0)

    assert fanout.ENRICH_COOLDOWN_SECONDS in clock.sleeps
    n = db.execute("SELECT COUNT(*) FROM enrichments WHERE status='pending'").fetchone()[0]
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


class Blocked(Exception):
    """Stand-in for requests.exceptions.HTTPError with a 403 response."""

    def __init__(self):
        self.response = type("R", (), {"status_code": 403})()


def test_blocked_rows_stay_pending(db, monkeypatch):
    """A 403 is the marketplace blocking us, not a bad listing: don't burn the rows."""
    n = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    for i in range(n):
        seed_pending(db, f"test:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class BlockedMP:
        def fetch_detail(self, listing):
            raise Blocked()

    def fake_sleep(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": BlockedMP()}, poll_seconds=2.0)

    row = db.execute(
        "SELECT status FROM enrichments WHERE listing_id='test:0'"
    ).fetchone()
    assert row[0] == "pending"


def test_cooldown_escalates_and_caps(db, monkeypatch):
    """Two consecutive blocked bursts for one marketplace: second pause doubles."""
    n = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    for burst in range(2):
        for i in range(n):
            seed_pending(db, f"test:{burst}-{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class BlockedMP:
        def fetch_detail(self, listing):
            raise Blocked()

    cooldowns = []

    def fake_sleep(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            cooldowns.append(s)
            if len(cooldowns) == 2:
                raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": BlockedMP()}, poll_seconds=2.0)

    assert cooldowns == [
        fanout.ENRICH_COOLDOWN_SECONDS,
        min(fanout.ENRICH_COOLDOWN_SECONDS * 2, fanout.ENRICH_MAX_COOLDOWN_SECONDS),
    ]




class B200(Exception):
    """429: rate-limit block shape."""

    def __init__(self):
        self.response = type("R", (), {"status_code": 429})()


class B503(Exception):
    """503: server-down block shape."""

    def __init__(self):
        self.response = type("R", (), {"status_code": 503})()


def test_dead_marketplace_never_delays_healthy_one(db, monkeypatch):
    """One blocked marketplace's cooldown must not stop the other's rows."""
    # Interleave so the good rows run before AND after the bad one trips.
    for i in range(5):
        seed_pending(db, f"bad:{i}")
        seed_pending(db, f"good:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class BlockedMP:
        def fetch_detail(self, listing):
            raise Blocked()

    cooldowns = []

    def fake_sleep(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            cooldowns.append(s)
            # The first long sleep must come only after all good rows are done.
            n = db.execute(
                "SELECT COUNT(*) FROM enrichments WHERE status='enriched'"
            ).fetchone()[0]
            assert n == 5
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker(
            {"bad": BlockedMP(), "good": GoodMP()}, poll_seconds=2.0
        )

    n_enriched = db.execute(
        "SELECT COUNT(*) FROM enrichments WHERE status='enriched'"
    ).fetchone()[0]
    assert n_enriched == 5
    n_pending = db.execute(
        "SELECT COUNT(*) FROM enrichments WHERE listing_id LIKE 'bad:%' AND status='pending'"
    ).fetchone()[0]
    assert n_pending == 5


def test_success_resets_that_marketplaces_cooldown(db, monkeypatch):
    """Blocked burst, recovery, blocked burst again: pause is 300s again, not 600s."""
    n = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    for i in range(n):
        seed_pending(db, f"flip:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class Flipping:
        """5 blocks, then one success, then blocks forever."""

        def __init__(self):
            self.calls = 0

        def fetch_detail(self, listing):
            self.calls += 1
            if self.calls == 6:
                return ListingDetail(description="back up")
            raise Blocked()

    cooldowns = []

    def fake_sleep(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            cooldowns.append(s)
            if len(cooldowns) == 2:
                raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"flip": Flipping()}, poll_seconds=2.0)

    # Reset on success: the second trip must NOT have doubled.
    assert cooldowns == [
        fanout.ENRICH_COOLDOWN_SECONDS,
        fanout.ENRICH_COOLDOWN_SECONDS,
    ]


def test_ordinary_errors_never_cool_marketplace(db, monkeypatch):
    """5 rows of model/parse errors leave the marketplace counter untouched: no 300s pause."""
    for i in range(5):
        seed_pending(db, f"err:{i}")
    seed_pending(db, "err:good")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class MostlyBoom:
        def fetch_detail(self, listing):
            if listing.id == "good":
                return ListingDetail(description="fine")
            raise Boom("model exploded")

    def fake_sleep(s):
        if s == 2.0:  # idle poll: queue drained
            raise StopIteration
        clock.sleep(s)

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"err": MostlyBoom()}, poll_seconds=2.0)

    assert all(s < fanout.ENRICH_COOLDOWN_SECONDS for s in clock.sleeps)
    n_failed = db.execute(
        "SELECT COUNT(*) FROM enrichments WHERE status='failed'"
    ).fetchone()[0]
    assert n_failed == 5


def test_all_cooling_sleeps_to_earliest(db, monkeypatch):
    """When every marketplace is cooling, the worker wakes at the earliest next-allowed."""
    n = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    # 'a' blocks 403, 'b' blocks 429; seed a first so it trips first.
    for i in range(n):
        seed_pending(db, f"a:{i}")
    for i in range(n):
        seed_pending(db, f"b:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class Blocked403:
        def fetch_detail(self, listing):
            raise Blocked()

    class Blocked429:
        def fetch_detail(self, listing):
            raise B200()

    def fake_sleep(s):
        clock.sleep(s)
        if s >= 200.0:  # first all-cooling wake
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"a": Blocked403(), "b": Blocked429()}, poll_seconds=2.0)

    # a trips at t=25 (5 rows x 5s), expiry t=325.
    # b trips at t=50, expiry t=350.
    # The worker must sleep 275s (to a's expiry), not 300s (to b's).
    assert 275.0 in clock.sleeps
    assert 300.0 not in clock.sleeps


def test_restart_resets_cooldowns(db, monkeypatch):
    """A worker restart gives every marketplace a fresh chance: no residual pause."""
    n = fanout.ENRICH_CONSECUTIVE_FAILURE_LIMIT
    for i in range(n):
        seed_pending(db, f"rst:{i}")
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class BlockedMP:
        def fetch_detail(self, listing):
            raise Blocked()

    # Run 1: the marketplace trips its cooldown.
    def stop_on_cooldown(s):
        clock.sleep(s)
        if s >= fanout.ENRICH_COOLDOWN_SECONDS:
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", stop_on_cooldown)
    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"rst": BlockedMP()}, poll_seconds=2.0)

    # Run 2: fresh worker, same blocked marketplace: it must try
    # immediately. The first sleep is the 5s pacing interval, not a 300s pause.
    clock2 = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock2.monotonic)

    def stop_after_two_rows(s):
        clock2.sleep(s)
        n_picked = clock2.calls = getattr(clock2, "calls", 0) + 1
        if n_picked >= 3:
            raise StopIteration

    monkeypatch.setattr(fanout.time, "sleep", stop_after_two_rows)
    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"rst": BlockedMP()}, poll_seconds=2.0)

    assert max(clock2.sleeps) < fanout.ENRICH_COOLDOWN_SECONDS


def test_progress_refresh_crash_does_not_kill_worker(db, monkeypatch):
    """A crash in progress bookkeeping must not strand the queue (2026-10-31)."""
    for i in range(2):
        seed_pending(db, f"test:{i}")
    db.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status) "
        "VALUES ('s', 'p', 'enriching')"
    )
    db.commit()
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    def boom_refresh(conn, sid):
        raise Boom("progress exploded")

    def fake_sleep(s):
        if s == 2.0:  # idle poll: everything processed
            raise StopIteration
        clock.sleep(s)

    monkeypatch.setattr(fanout, "_refresh_progress", boom_refresh)
    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": GoodMP()}, poll_seconds=2.0)

    n = db.execute("SELECT COUNT(*) FROM enrichments WHERE status='enriched'").fetchone()[0]
    assert n == 2


def test_ordinary_fail_still_completes_search(db, monkeypatch):
    """Regression #75: the last pending row failing ordinarily (not blocked)
    must still let the progress-refresh pass flip the search to 'complete'."""
    seed_pending(db, "test:0")
    db.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status, listing_ids) "
        "VALUES ('s', 'p', 'enriching', ?)",
        (json.dumps({"test:0": "match"}),),
    )
    db.commit()
    clock = FakeClock()
    monkeypatch.setattr(fanout.time, "monotonic", clock.monotonic)

    class BadMP:
        def fetch_detail(self, listing):
            raise Boom("model exploded")

    def fake_sleep(s):
        if s == 2.0:  # idle poll: the row was processed, stop the worker
            raise StopIteration
        clock.sleep(s)

    monkeypatch.setattr(fanout.time, "sleep", fake_sleep)
    monkeypatch.setattr(fanout.identity, "update_identity_from_search", lambda c, sid: None)

    with pytest.raises(StopIteration):
        fanout.enrichment_worker({"test": BadMP()}, poll_seconds=2.0)

    row = db.execute(
        "SELECT status FROM enrichments WHERE listing_id='test:0'"
    ).fetchone()
    assert row[0] == "failed"
    status = db.execute(
        "SELECT status FROM bargain_searches WHERE id=1"
    ).fetchone()[0]
    assert status == "complete"
