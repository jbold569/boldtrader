"""Ticket #72 — scheduler daemon: 06:00 daily sweep with boot catch-up.

The clock. Fires the Daily Sweep (run_sweep, ticket #71) at 06:00 local
every day. At boot, if the last recorded sweep is older than ~20 hours —
or none ever ran — it fires immediately (catch-up), so crashes and
reboots self-heal instead of silently skipping a day. Lives inside the
boldtrader server as a daemon thread (ADR 0014): no cron, no side
process. A sweep that raises is caught, logged, and recorded as a
'failed' sweep_runs row; the loop keeps its schedule.

All time flows through injected dependencies so the whole thread is
testable without waiting for mornings: `clock` provides monotonic()/
sleep() (same convention as run_sweep) and `now_fn` returns the local
wall clock as a naive datetime.
"""

from __future__ import annotations
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from .db import get_connection
from .sweep import run_sweep

log = logging.getLogger(__name__)

SWEEP_HOUR = 6
CATCH_UP_THRESHOLD_HOURS = 20.0
# Sleep is sliced so a long wait never blocks on one giant sleep.
SLEEP_SLICE_SECONDS = 300


def _seconds_until_next_0600(now: datetime) -> float:
    """Seconds from local `now` until the next 06:00 (strictly after)."""
    target = now.replace(hour=SWEEP_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _should_catch_up(latest_row, now: datetime, threshold_hours: float = CATCH_UP_THRESHOLD_HOURS) -> bool:
    """True when the last sweep is too old to trust (or never happened).

    `latest_row` is (started_at, finished_at) from sweep_runs, or None.
    An unfinished row (finished_at NULL, e.g. a crash mid-sweep) is
    judged by when it started."""
    if latest_row is None:
        return True
    started_at, finished_at = latest_row
    ref = finished_at or started_at
    last = datetime.fromisoformat(ref)
    if last.tzinfo is None:  # defensive: treat naive rows as UTC
        last = last.replace(tzinfo=timezone.utc)
    age = (now.astimezone(timezone.utc) - last).total_seconds()
    return age > threshold_hours * 3600


def _latest_run(conn):
    return conn.execute(
        "SELECT started_at, finished_at FROM sweep_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _record_failure(store, exc: Exception) -> None:
    """Persist a crash the sweep itself never got to record."""
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        conn = store if store is not None else get_connection()
        conn.execute(
            "INSERT INTO sweep_runs (started_at, finished_at, outcome, report) "
            "VALUES (?, ?, 'failed', ?)",
            (stamp, stamp, json.dumps({"error": str(exc) or type(exc).__name__})),
        )
        conn.commit()
    except Exception:
        # The DB is the casualty, not more to report from here.
        log.exception("could not record failed sweep run")


def _fire(marketplaces, store) -> None:
    """One scheduled sweep; a crash is logged and recorded, never fatal."""
    try:
        run_sweep(marketplaces, store)
    except Exception as exc:
        log.exception("scheduled daily sweep failed")
        _record_failure(store, exc)


def _sleep_until_0600(now_fn, clock) -> None:
    """Wait for the next 06:00 in bounded slices, driven by the clock."""
    target = clock.monotonic() + _seconds_until_next_0600(now_fn())
    while True:
        remaining = target - clock.monotonic()
        if remaining <= 0:
            return
        clock.sleep(min(remaining, SLEEP_SLICE_SECONDS))


def scheduler_loop(marketplaces, store=None, now_fn=datetime.now, clock=None) -> None:
    """The schedule: catch-up now if stale, then fire every day at 06:00."""
    if clock is None:
        clock = time
    if store is None:
        store = get_connection()
    latest = _latest_run(store)
    if _should_catch_up(latest, now_fn()):
        _fire(marketplaces, store)
    while True:
        _sleep_until_0600(now_fn, clock)
        _fire(marketplaces, store)


def start_scheduler(marketplaces, store=None) -> "threading.Thread":
    """Start the scheduler as a daemon thread and return it."""
    t = threading.Thread(
        target=scheduler_loop,
        args=(marketplaces,),
        kwargs={"store": store},
        daemon=True,
        name="scheduler",
    )
    t.start()
    return t
