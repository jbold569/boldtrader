"""Price refresh for a single stored live Listing (ticket #67).

Re-fetch one Listing's current asking price and shipping from its
Marketplace via the existing fetch_detail convention, replace the frozen
first-sight values in the stored row in place, and record a fresh Price
Observation whose effective price is computed from the newly fetched
numbers through the shared deal-math path (ticket #64 spec).

A Correction wins: a listing whose enrichment was hand-corrected
(enrichments.corrected) is skipped entirely — user truth outranks the
fetch, the same freeze rule the Enrichment worker applies (GLOSSARY:
Correction, ticket #56).

A fetch failure is reported per-listing, never fatal: the caller gets a
result dict it can inspect, and the stored data is left untouched.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

from . import dealmath
from .marketplace import Listing, ListingDetail, Marketplace

log = logging.getLogger(__name__)

# Pacing matches enrichment (ENRICH_MIN_INTERVAL_SECONDS in fanout). The
# cooldown constants carry the same escalation shape as #66 (300s,
# doubling, capped) but live in this pass: #66's state is local to
# enrichment_worker and is not exported.
REFRESH_MIN_INTERVAL_SECONDS = 5.0
REFRESH_CONSECUTIVE_FAILURE_LIMIT = 5
REFRESH_COOLDOWN_SECONDS = 300.0
REFRESH_MAX_COOLDOWN_SECONDS = 3600.0


def _current_ask(detail: ListingDetail) -> float | None:
    """The current ask carried by a fetched detail record."""
    return detail.price


def refresh_listing_price(
    conn: sqlite3.Connection, listing_id: str, marketplace: Marketplace
) -> dict:
    """Refresh one listing's ask + shipping and record a Price Observation.

    Returns a result dict: ``{"status": "refreshed"|"failed"|"skipped_corrected",
    "listing_id": ..., ...}``. Never raises: a failed fetch is reported in the
    result and the stored row stays exactly as it was.
    """
    row = conn.execute(
        "SELECT l.raw, l.product_identity_id, e.corrected, e.condition, e.bundle, "
        "p.description FROM listings l "
        "LEFT JOIN enrichments e ON e.listing_id = l.id "
        "LEFT JOIN product_identities p ON p.id = l.product_identity_id "
        "WHERE l.id=?",
        (listing_id,),
    ).fetchone()
    if row is None:
        return {
            "status": "failed",
            "listing_id": listing_id,
            "error": f"no stored listing {listing_id}",
        }
    raw, pid, corrected, condition, bundle_json, identity_desc = row
    if corrected:
        return {"status": "skipped_corrected", "listing_id": listing_id}
    if pid is None:
        return {
            "status": "failed",
            "listing_id": listing_id,
            "error": "listing has no mapped Product Identity",
        }

    try:
        listing = Listing(**json.loads(raw))
        detail = marketplace.fetch_detail(listing)
    except Exception as exc:
        log.warning("price refresh fetch failed for %s: %s", listing_id, exc)
        return {"status": "failed", "listing_id": listing_id, "error": str(exc)}

    ask = _current_ask(detail)
    if ask is None:
        return {
            "status": "failed",
            "listing_id": listing_id,
            "error": "marketplace detail carried no ask price",
        }

    bundle = json.loads(bundle_json) if bundle_json else None
    flip = dealmath.flip_value(conn, bundle, identity_desc or "") if bundle else 0.0
    effective = dealmath.effective_price(float(ask), detail.shipping_cost, flip)

    data = json.loads(raw)
    data["price"] = ask
    try:
        conn.execute(
            "UPDATE listings SET raw=?, shipping_cost=?, "
            "availability_checked_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(data), detail.shipping_cost, listing_id),
        )
        dealmath.record_observation(
            conn, listing_id, pid, condition or "complete", effective
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.warning("price refresh write failed for %s: %s", listing_id, exc)
        return {"status": "failed", "listing_id": listing_id, "error": str(exc)}

    return {
        "status": "refreshed",
        "listing_id": listing_id,
        "asking_price": ask,
        "shipping_cost": detail.shipping_cost,
        "effective_price": effective,
    }


def _select_refresh_targets(conn: sqlite3.Connection) -> list[tuple[str, float | None]]:
    """Every live matched Listing whose price is not user-Corrected.

    "Matched" means the listing carries a 'match' verdict in at least one
    Bargain Search's verdict map (ticket #70 selection rule). First
    occurrence order across searches is preserved.
    """
    matched: list[str] = []
    seen: set[str] = set()
    for (verdicts_json,) in conn.execute(
        "SELECT listing_ids FROM bargain_searches ORDER BY id"
    ):
        for lid, verdict in json.loads(verdicts_json or "{}").items():
            if verdict == "match" and lid not in seen:
                seen.add(lid)
                matched.append(lid)
    if not matched:
        return []
    placeholders = ",".join("?" * len(matched))
    rows = conn.execute(
        f"SELECT l.id, l.raw FROM listings l "
        f"LEFT JOIN enrichments e ON e.listing_id = l.id "
        f"WHERE l.availability = 'live' AND COALESCE(e.corrected, 0) = 0 "
        f"AND l.id IN ({placeholders})",
        matched,
    ).fetchall()
    targets = []
    for lid, raw in rows:
        try:
            stored_price = json.loads(raw).get("price")
        except (TypeError, ValueError):
            stored_price = None
        targets.append((lid, float(stored_price) if stored_price is not None else None))
    return targets


def _previous_effective(conn: sqlite3.Connection, listing_id: str,
                       fallback: float | None) -> float | None:
    """The listing's last recorded effective price, or its frozen ask."""
    row = conn.execute(
        "SELECT effective_price FROM price_observations "
        "WHERE listing_id=? ORDER BY id DESC LIMIT 1",
        (listing_id,),
    ).fetchone()
    if row is not None:
        return float(row[0])
    return fallback


def bulk_refresh_price(
    conn: sqlite3.Connection,
    marketplaces: dict[str, Marketplace],
    clock=None,
) -> dict:
    """Sweep phase B: refresh every live matched listing (ticket #70).

    Drives refresh_listing_price over the selection with at least
    REFRESH_MIN_INTERVAL_SECONDS between marketplace calls. Carries its
    own per-marketplace escalating cooldown (#66 shape: REFRESH_CONSECUTIVE_FAILURE_LIMIT
    consecutive failures trip a cooldown that starts at 300s and doubles
    up to the cap, reset by that marketplace's next success) so one dead
    marketplace never stalls the others. A listing whose marketplace is
    cooling is skipped and counted in blocked_marketplaces. One listing's
    failure never aborts the pass.

    Returns the digest report: refreshed/failed counts, per-marketplace
    blocked-skip counts, the price-drop summary (total + three largest by
    absolute dollars with listing ids), and run start/end timestamps.
    """
    if clock is None:
        clock = time
    started_at = datetime.now(timezone.utc).isoformat()
    targets = _select_refresh_targets(conn)

    failures: dict[str, int] = {}
    cooldown: dict[str, float] = {}
    next_allowed: dict[str, float] = {}
    blocked_skips: dict[str, int] = {}
    drops: list[dict] = []
    refreshed = 0
    failed = 0

    for lid, stored_price in targets:
        mp_name = lid.split(":", 1)[0]
        mp = marketplaces.get(mp_name)
        if mp is None:
            failed += 1
            log.warning("no marketplace object for %s", lid)
            continue
        now = clock.monotonic()
        if now < next_allowed.get(mp_name, 0.0):
            blocked_skips[mp_name] = blocked_skips.get(mp_name, 0) + 1
            continue
        wait = next_allowed.get("__pace__", 0.0) - now
        if wait > 0:
            clock.sleep(wait)
        prev = _previous_effective(conn, lid, stored_price)
        result = refresh_listing_price(conn, lid, mp)
        clock_now = clock.monotonic()
        next_allowed["__pace__"] = clock_now + REFRESH_MIN_INTERVAL_SECONDS
        if result["status"] == "refreshed":
            refreshed += 1
            failures[mp_name] = 0
            cooldown[mp_name] = REFRESH_COOLDOWN_SECONDS
            next_allowed.pop(mp_name, None)
            new_eff = result["effective_price"]
            if prev is not None and new_eff < prev:
                drops.append({
                    "listing_id": lid,
                    "amount": round(prev - new_eff, 2),
                    "old_effective": prev,
                    "new_effective": new_eff,
                })
        else:
            failed += 1
            failures[mp_name] = failures.get(mp_name, 0) + 1
            if failures[mp_name] >= REFRESH_CONSECUTIVE_FAILURE_LIMIT:
                cd = cooldown.get(mp_name, REFRESH_COOLDOWN_SECONDS)
                log.warning(
                    "%s: %d consecutive refresh failures; cooling %.0fs",
                    mp_name, failures[mp_name], cd,
                )
                next_allowed[mp_name] = clock_now + cd
                failures[mp_name] = 0
                cooldown[mp_name] = min(cd * 2, REFRESH_MAX_COOLDOWN_SECONDS)

    drops.sort(key=lambda d: d["amount"], reverse=True)
    return {
        "refreshed_count": refreshed,
        "failed_count": failed,
        "blocked_marketplaces": blocked_skips,
        "price_drops": {"count": len(drops), "top_3": drops[:3]},
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }
