"""Bargain Search data mutations shared by the JSON API.

Ticket #51 (M8) deleted the legacy Python-rendered enhanced view out of
this module. What remains is the database behaviors the API delegates:
rejection as a live correction to the mapped Product Identity (ticket
#61), and authored-description save with enrichment re-queue.
"""

from __future__ import annotations

import json
import sqlite3

from . import dealmath, identity


def reject_listing(
    conn: sqlite3.Connection, search_id: int, listing_id: str, reason: str
) -> None:
    """Reject a card: a live correction to the Product Identity, not just
    an exclusion note for the next sift. One transaction: the reject row
    (deduped by search+listing), the deletion of that listing's price
    observations under the search's mapped identity, and the reason
    appended verbatim to the identity's Exclusions block (ticket #61).
    The search-level exclusion list still rides along for the next sift."""
    already = conn.execute(
        "SELECT 1 FROM rejects WHERE bargain_search_id=? AND listing_id=?",
        (search_id, listing_id),
    ).fetchone()
    if already is None:
        conn.execute(
            "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, ?, ?)",
            (search_id, listing_id, reason),
        )
    exclusions = json.loads(
        conn.execute(
            "SELECT exclusions FROM bargain_searches WHERE id=?", (search_id,)
        ).fetchone()[0]
    )
    if reason not in exclusions:
        exclusions.append(reason)
        conn.execute(
            "UPDATE bargain_searches SET exclusions=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (json.dumps(exclusions), search_id),
        )
    mapped = conn.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()[0]
    if mapped is not None:
        conn.execute(
            "DELETE FROM price_observations "
            "WHERE listing_id=? AND product_identity_id=?",
            (listing_id, mapped),
        )
        desc = conn.execute(
            "SELECT description FROM product_identities WHERE id=?", (mapped,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE product_identities SET description=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (identity.append_exclusion(desc, reason), mapped),
        )
    conn.commit()


def set_authored_description(
    conn: sqlite3.Connection, listing_id: str, text: str
) -> None:
    """Store the user's authored description (empty clears it) and re-queue
    the listing for enrichment so the AI result incorporates the new text."""
    text = (text or "").strip()
    conn.execute(
        "UPDATE listings SET authored_description=? WHERE id=?",
        (text or None, listing_id),
    )
    conn.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES (?, 'pending') "
        "ON CONFLICT(listing_id) DO UPDATE SET status='pending'",
        (listing_id,),
    )
    conn.commit()


def restore_correction(
    conn: sqlite3.Connection, search_id: int, listing_id: str, reason: str
) -> None:
    """Reverse a rejection's identity correction (ticket #61): the reason
    line is dropped from the mapped identity's Exclusions block and a
    fresh price observation is recorded from the listing's current
    data — the same observation the pipeline would have made had the
    rejection never happened. The search-level exclusion rebuild stays
    with the API handler."""
    mapped = conn.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()[0]
    if mapped is not None:
        desc = conn.execute(
            "SELECT description FROM product_identities WHERE id=?", (mapped,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE product_identities SET description=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (identity.remove_exclusion(desc, reason), mapped),
        )
    row = conn.execute(
        "SELECT raw, shipping_cost, product_identity_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    data = json.loads(row[0])
    pid = row[2] if row[2] is not None else mapped
    if pid is None:
        # No identity to record against: nothing to re-observe.
        conn.commit()
        return
    condition_row = conn.execute(
        "SELECT condition FROM enrichments WHERE listing_id=? AND status='enriched'",
        (listing_id,),
    ).fetchone()
    condition = (condition_row[0] if condition_row else None) or "complete"
    effective = dealmath.effective_price(
        float(data.get("price") or 0.0), row[1], 0.0
    )
    dealmath.record_observation(conn, listing_id, pid, condition, effective)
    conn.commit()
