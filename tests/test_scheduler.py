"""Ticket #72 — scheduler daemon: 06:00 daily sweep with boot catch-up.

All time logic is injected: a FakeTime plays both the monotonic clock and
the local wall clock (now_fn), so the loop can cross 06:00 without
waiting for morning. run_sweep is swapped for a fake that records each
fire and can blow up to prove the loop survives.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.db import init_db
from src import scheduler


class StopLoop(BaseException):
    """Sentinel that yanks the test out of the endless scheduler loop.

    BaseException on purpose: scheduler_loop catches Exception, and it
    must — a plain Exception here would be swallowed like a sweep error."""


class FakeTime:
    """time.monotonic/sleep stand-in whose sleep also advances the wall clock."""

    def __init__(self, start: datetime):
        self.start = start
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> datetime:
        return self.start + timedelta(seconds=self.now)


class FakeSweep:
    """run_sweep stand-in: records the local time of each fire.

    fail_calls is the set of 1-based call numbers that raise RuntimeError.
    Once stop_after fires have been recorded, raises StopLoop."""

    def __init__(self, time_fn, fail_calls=(), stop_after=1):
        self.time_fn = time_fn
        self.fail_calls = set(fail_calls)
        self.stop_after = stop_after
        self.calls: list[datetime] = []

    def __call__(self, marketplaces, store, clock=None):
        self.calls.append(self.time_fn())
        n = len(self.calls)
        if n in self.fail_calls:
            raise RuntimeError("sweep exploded")
        if n >= self.stop_after:
            raise StopLoop()
        return {"outcome": "complete"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "sched.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def iso_ago(base: datetime, hours: float) -> str:
    """UTC ISO string for the moment `hours` before naive-local `base`."""
    return (base - timedelta(hours=hours)).astimezone(timezone.utc).isoformat()


def seed_run(conn, base, started_hours_ago, finished_hours_ago=None):
    """Insert a sweep_runs row. No finished_hours_ago leaves it 'running'."""
    started = iso_ago(base, started_hours_ago)
    if finished_hours_ago is None:
        conn.execute(
            "INSERT INTO sweep_runs (started_at, outcome) VALUES (?, 'running')",
            (started,),
        )
    else:
        conn.execute(
            "INSERT INTO sweep_runs (started_at, finished_at, outcome) VALUES (?, ?, 'complete')",
            (started, iso_ago(base, finished_hours_ago)),
        )
    conn.commit()


# --- pure predicate ---------------------------------------------------


def test_predicate_never_swept_fires():
    assert scheduler._should_catch_up(None, datetime(2026, 11, 1, 14, 0)) is True


def test_predicate_fresh_sweep_does_not_fire():
    now = datetime(2026, 11, 1, 14, 0)
    row = (iso_ago(now, 3), iso_ago(now, 2))  # finished 2 h ago
    assert scheduler._should_catch_up(row, now) is False


def test_predicate_stale_sweep_fires():
    now = datetime(2026, 11, 1, 14, 0)
    row = (iso_ago(now, 22), iso_ago(now, 21))  # finished 21 h ago
    assert scheduler._should_catch_up(row, now) is True


def test_predicate_unfinished_run_uses_started_at():
    now = datetime(2026, 11, 1, 14, 0)
    stale_running = (iso_ago(now, 21), None)
    assert scheduler._should_catch_up(stale_running, now) is True
    fresh_running = (iso_ago(now, 2), None)
    assert scheduler._should_catch_up(fresh_running, now) is False


# --- next-06:00 computation -------------------------------------------


def test_seconds_until_next_0600_after_morning():
    assert scheduler._seconds_until_next_0600(datetime(2026, 11, 1, 14, 0)) == 16 * 3600


def test_seconds_until_next_0600_before_morning():
    assert scheduler._seconds_until_next_0600(datetime(2026, 11, 1, 5, 0)) == 3600


def test_seconds_until_next_0600_exactly_at_time_wraps():
    # At exactly 06:00 "next" is tomorrow, never 0 (no double fire).
    assert scheduler._seconds_until_next_0600(datetime(2026, 11, 1, 6, 0)) == 24 * 3600


# --- loop scenarios ----------------------------------------------------

def test_boot_never_swept_fires_immediately(db, monkeypatch):
    ft = FakeTime(datetime(2026, 11, 1, 14, 0))
    fake = FakeSweep(ft, stop_after=1)
    monkeypatch.setattr(scheduler, "run_sweep", fake)
    with pytest.raises(StopLoop):
        scheduler.scheduler_loop({}, db, now_fn=ft, clock=ft)
    assert len(fake.calls) == 1
    assert fake.calls[0] == ft.start  # no waiting happened first
    assert ft.sleeps == []


def test_boot_stale_last_sweep_catch_up_fires(db, monkeypatch):
    base = datetime(2026, 11, 1, 14, 0)
    seed_run(db, base, started_hours_ago=22, finished_hours_ago=21)
    ft = FakeTime(base)
    fake = FakeSweep(ft, stop_after=1)
    monkeypatch.setattr(scheduler, "run_sweep", fake)
    with pytest.raises(StopLoop):
        scheduler.scheduler_loop({}, db, now_fn=ft, clock=ft)
    assert len(fake.calls) == 1
    assert fake.calls[0] == base
    assert ft.sleeps == []

def test_boot_fresh_sweep_waits_for_next_0600(db, monkeypatch):
    base = datetime(2026, 11, 1, 14, 0)
    seed_run(db, base, started_hours_ago=3, finished_hours_ago=2)
    ft = FakeTime(base)
    fake = FakeSweep(ft, stop_after=1)
    monkeypatch.setattr(scheduler, "run_sweep", fake)
    with pytest.raises(StopLoop):
        scheduler.scheduler_loop({}, db, now_fn=ft, clock=ft)
    assert len(fake.calls) == 1
    # First fire is tomorrow 06:00, after ~16 h of chunked sleeping.
    assert fake.calls[0] == datetime(2026, 11, 2, 6, 0)
    assert sum(ft.sleeps) == 16 * 3600
    assert ft.sleeps[0] <= 300  # sleeps are bounded slices

def test_clock_crosses_0600_fires(db, monkeypatch):
    base = datetime(2026, 11, 2, 5, 59)
    seed_run(db, base, started_hours_ago=1)  # fresh: no catch-up
    ft = FakeTime(base)
    fake = FakeSweep(ft, stop_after=1)
    monkeypatch.setattr(scheduler, "run_sweep", fake)
    with pytest.raises(StopLoop):
        scheduler.scheduler_loop({}, db, now_fn=ft, clock=ft)
    assert fake.calls[0] == datetime(2026, 11, 2, 6, 0)

def test_sweep_exception_caught_recorded_next_fire_happens(db, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    base = datetime(2026, 11, 1, 14, 0)
    ft = FakeTime(base)
    # First fire (catch-up on empty DB) explodes; second (06:00) succeeds.
    fake = FakeSweep(ft, fail_calls={1}, stop_after=2)
    monkeypatch.setattr(scheduler, "run_sweep", fake)
    with pytest.raises(StopLoop):
        scheduler.scheduler_loop({}, db, now_fn=ft, clock=ft)
    assert len(fake.calls) == 2
    assert fake.calls[0] == base
    assert fake.calls[1] == datetime(2026, 11, 2, 6, 0)
    # The failed fire was logged, and a 'failed' row recorded for it.
    assert "sweep failed" in caplog.text.lower()
    outcomes = [
        r[0] for r in db.execute("SELECT outcome FROM sweep_runs ORDER BY id")
    ]
    assert "failed" in outcomes

def test_two_consecutive_crashes_do_not_stop_the_loop(db, monkeypatch):
    base = datetime(2026, 11, 1, 14, 0)
    ft = FakeTime(base)
    fake = FakeSweep(ft, fail_calls={1, 2}, stop_after=3)
    monkeypatch.setattr(scheduler, "run_sweep", fake)
    with pytest.raises(StopLoop):
        scheduler.scheduler_loop({}, db, now_fn=ft, clock=ft)
    assert len(fake.calls) == 3


# --- thread plumbing ----------------------------------------------------


def test_start_scheduler_returns_started_daemon(db):
    started = threading.Event()

    def fake_loop(marketplaces, store=None, now_fn=None, clock=None):
        started.set()
        threading.Event().wait(5)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(scheduler, "scheduler_loop", fake_loop)
    t = scheduler.start_scheduler({}, store=db)
    try:
        assert t.daemon is True
        assert started.wait(2)
        assert t.is_alive()
    finally:
        monkey.undo()
