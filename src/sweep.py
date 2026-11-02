"""Daily sweep runner (ticket #71).

The chain: Phase A re-fans every Bargain Search serially (each under a
~20-minute cap, a raising search contained); the enrichment queue drains;
Phase B bulk-refreshes live prices; Phase C reresolves the night's
accumulated stale union and clears it. The whole run persists to a
sweep_runs record — started, finished, outcome, report — so the
catch-up predicate and the digest both read it from the DB.

Everything is injected (marketplaces, store, clock): no module-level
mutable state, so the whole choreography is testable with fakes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from .fanout import fan_out
from .pricerefresh import bulk_refresh_price
from .api import reresolve_by_ids
from . import stale
from . import dealmath
from . import digest

log = logging.getLogger(__name__)

# ~20 minutes per search's fan-out (ticket #62): one hung marketplace
# must not stall the morning.
PER_SEARCH_TIMEOUT_SECONDS = 1200
# Virtual-time jump per drain/liveness poll.
POLL_SECONDS = 30.0
# Real-time breath per liveness poll: the virtual clock advances faster
# than real time, and the watchdog must leave the fan-out real time to
# finish before declaring it dead.
WAIT_SLICE_SECONDS = 0.2
# Generous bound on the post-phase-A enrichment drain: if the queue
# never empties within an hour, record it and proceed anyway.
DRAIN_TIMEOUT_SECONDS = 3600.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity_desc(conn, search_id: int):
    """The search's mapped identity description, or None."""
    row = conn.execute(
        "SELECT description FROM product_identities "
        "WHERE id=(SELECT product_identity_id FROM bargain_searches WHERE id=?)",
        (search_id,),
    ).fetchone()
    return row[0] if row else None


def _best_margin(conn, verdicts: dict) -> float | None:
    """Largest margin_pct across the search's matched listings, or None
    when nothing qualifies (no matches, no computable fair price).
    Same formula as list_deals: (fair - effective) / fair * 100."""
    best: float | None = None
    lids = [lid for lid, v in verdicts.items() if v in ("match", "unsure")]
    for lid in lids:
        row = conn.execute(
            "SELECT l.raw, l.shipping_cost, l.product_identity_id, "
            "e.condition, e.bundle, e.product "
            "FROM listings l LEFT JOIN enrichments e ON e.listing_id = l.id "
            "WHERE l.id=?",
            (lid,),
        ).fetchone()
        if row is None:
            continue
        raw, shipping, pid, cond, bun, prod = row
        if pid is None:
            continue
        data = json.loads(raw)
        price = data.get("price")
        if price is None:
            continue
        condition = cond or "complete"
        fair = dealmath.fair_price(conn, pid, condition)
        if fair is None:
            continue
        bundle = json.loads(bun) if bun else None
        identity_desc = None
        if prod:
            try:
                identity_desc = (json.loads(prod) or {}).get("description")
            except ValueError:
                identity_desc = None
        flip = (
            dealmath.flip_value(conn, bundle, identity_desc or "") if bundle else 0.0
        )
        effective = dealmath.effective_price(float(price), shipping, flip)
        margin = (fair - effective) / fair * 100.0
        if best is None or margin > best:
            best = margin
    return best


def _fan_worker(
    marketplaces, search_id: int, location, errors: list, done: threading.Event
) -> None:
    """Thread body: fan_out's exception, if any, lands in `errors` so the
    waiting sweep can contain it (join() never surfaces it); `done`
    signals the fan-out returned however it ended."""
    try:
        fan_out(marketplaces, search_id, location)
    except Exception as exc:
        log.exception("sweep: fan-out #%s raised", search_id)
        errors.append(str(exc) or type(exc).__name__)
    finally:
        done.set()


def _run_search_with_timeout(marketplaces, conn, search_id: int, clock) -> dict:
    """Phase A step for one search: fan out in a watchdog thread, stop
    waiting after PER_SEARCH_TIMEOUT_SECONDS.

    Limitation: Python cannot forcibly kill a thread. On timeout the
    record says so and the sweep moves on; the orphaned fan-out keeps
    running until it finishes itself, harmlessly — every write it makes
    is the same idempotent per-search bookkeeping."""
    row = conn.execute(
        "SELECT location, summary FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    location = row[0] if row else None
    summary = row[1] if row else None
    before_desc = _identity_desc(conn, search_id)
    errors: list[str] = []
    done = threading.Event()
    t = threading.Thread(
        target=_fan_worker,
        args=(marketplaces, search_id, location, errors, done),
        daemon=True,
    )
    deadline = clock.monotonic() + PER_SEARCH_TIMEOUT_SECONDS
    t.start()
    while not done.wait(WAIT_SLICE_SECONDS) and clock.monotonic() < deadline:
        clock.sleep(POLL_SECONDS)
    rec: dict = {"search_id": search_id, "summary": summary}
    if not done.is_set():
        rec.update(
            new_listing_count=0,
            match_count=0,
            failed=True,
            timed_out=True,
            error=f"timed out after {PER_SEARCH_TIMEOUT_SECONDS}s",
            best_margin_pct=None,
        )
        return rec
    if errors:
        rec.update(
            new_listing_count=0,
            match_count=0,
            failed=True,
            timed_out=False,
            error=errors[0],
            best_margin_pct=None,
        )
        return rec
    verdict_row = conn.execute(
        "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    verdicts = json.loads(verdict_row[0]) if verdict_row and verdict_row[0] else {}
    rec["new_listing_count"] = len(verdicts)
    rec["match_count"] = sum(1 for v in verdicts.values() if v in ("match", "unsure"))
    rec["failed"] = False
    rec["timed_out"] = False
    rec["best_margin_pct"] = _best_margin(conn, verdicts)
    after = conn.execute(
        "SELECT description, matched_evidence FROM product_identities "
        "WHERE id=(SELECT product_identity_id FROM bargain_searches WHERE id=?)",
        (search_id,),
    ).fetchone()
    after_desc = after[0] if after else None
    # A rewrite only counts when the description actually moved; the
    # #68 gate skip leaves it untouched, so it never lands here.
    if after_desc and after_desc != before_desc:
        rec["old_desc"] = before_desc
        rec["new_desc"] = after_desc
        rec["evidence_count"] = len(json.loads((after[1] if after else None) or "[]"))
    return rec


def _pending_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM enrichments WHERE status='pending'"
    ).fetchone()[0]


def run_sweep(marketplaces: dict, store, clock=None) -> dict:
    """Run the full Daily Sweep chain and persist the record (ticket #71).

    `store` is the open sqlite connection; `clock` supplies
    monotonic()/sleep() (real `time` by default). Returns the
    SweepReport dict: per-search results, the phase B price-refresh
    report, the phase C reresolve result, the overall outcome, and the
    run's start/finish timestamps."""
    if clock is None:
        clock = time
    conn = store
    started_at = _iso_now()
    cur = conn.execute(
        "INSERT INTO sweep_runs (started_at, outcome) VALUES (?, 'running')",
        (started_at,),
    )
    run_id = cur.lastrowid
    conn.commit()
    # The board as it is now: a delete mid-sweep doesn't shift iteration.
    search_ids = [
        r[0]
        for r in conn.execute("SELECT id FROM bargain_searches ORDER BY id").fetchall()
    ]

    try:
        # Phase A: serial fan-out, each search contained.
        search_results = [
            _run_search_with_timeout(marketplaces, conn, sid, clock)
            for sid in search_ids
        ]

        # Let the enrichment worker drain every pending row before
        # touching prices: refreshing asks mid-enrichment mixes stale
        # judgments into the night's numbers.
        drain_deadline = clock.monotonic() + DRAIN_TIMEOUT_SECONDS
        pending = _pending_count(conn)
        while pending > 0 and clock.monotonic() < drain_deadline:
            clock.sleep(POLL_SECONDS)
            pending = _pending_count(conn)
        enrichment_drained = pending == 0

        # Phase B: bulk price refresh over live matches.
        price_report = bulk_refresh_price(conn, marketplaces, clock=clock)

        # Phase C: reresolve the accumulated stale union (NOT the
        # per-search stale_lids column — the union survives the fan-out
        # resets, ticket #69), then clear the night's table.
        union = stale.read_stale_union(conn)
        if union:
            reresolve_result = reresolve_by_ids(conn, sorted(union))
            conn.execute("DELETE FROM stale_union")
            conn.commit()
        else:
            reresolve_result = {
                "moves": [],
                "total": 0,
                "moved": 0,
                "unchanged": 0,
                "skipped_corrected": 0,
            }

        blocked = bool(price_report.get("blocked_marketplaces"))
        any_search_failed = any(r["failed"] for r in search_results)
        outcome = (
            "partial"
            if (any_search_failed or blocked or not enrichment_drained)
            else "complete"
        )
        report = {
            "started_at": started_at,
            "finished_at": _iso_now(),
            "searches": search_results,
            "price_refresh": price_report,
            "reresolve": reresolve_result,
            "enrichment_drained": enrichment_drained,
            "outcome": outcome,
        }
    except Exception as exc:
        # The chain itself could not run; the failure is the record.
        log.exception("sweep run failed")
        outcome = "failed"
        report = {
            "started_at": started_at,
            "finished_at": _iso_now(),
            "error": str(exc) or type(exc).__name__,
            "outcome": "failed",
        }

    conn.execute(
        "UPDATE sweep_runs SET finished_at=?, outcome=?, report=? WHERE id=?",
        (report["finished_at"], outcome, json.dumps(report), run_id),
    )
    conn.commit()
    if outcome != "failed":
        # The morning digest rides the same report: file first, Signal second.
        digest.deliver_digest(report)
    return report
