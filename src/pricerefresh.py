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

from . import dealmath
from .marketplace import Listing, ListingDetail, Marketplace

log = logging.getLogger(__name__)


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
