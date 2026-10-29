"""Bargain Search data mutations shared by the JSON API.

Ticket #51 (M8) deleted the legacy Python-rendered enhanced view out of
this module: card assembly, rendering, and the search-list page all live in
the React SPA now (see docs/frontend-architecture.md). What remains is the
two database behaviors the API delegates: rejection with exclusion-list
feedback, and authored-description save with enrichment re-queue.
"""

from __future__ import annotations

import json
import sqlite3


def reject_listing(
    conn: sqlite3.Connection, search_id: int, listing_id: str, reason: str
) -> None:
    """Reject a card: record it and feed the exclusion list for the next sift."""
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
