"""Fan-out + enrichment worker (ticket 05).

On confirmation, fan every curated query across all marketplaces (paginated,
tolerant of single-marketplace failure), persist each new listing, and triage it.
Listings judged match/unsure enter the enrichment queue. A single background
worker drains the queue: fetch_detail + enrich, retry once, then mark failed.
The queue is the database: status columns make it restart-resumable.

Search status flow: 'running' (fan-out in progress) -> 'enriching' (fan-out
done, enrichment pending) -> 'complete' (queue drained).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

from . import router
from .db import get_connection
from .marketplace import Listing, Marketplace


def fan_out(
    marketplaces: dict[str, Marketplace],
    search_id: int,
    location: str | None = None,
) -> None:
    """Run every query across every marketplace; persist + triage new listings.

    One thread per marketplace (same tolerance pattern as _search_all): a
    single marketplace failing is a note, not an error. Match/unsure listings
    are queued for enrichment and tracked in the search's listing_ids (the
    progress denominator).
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT queries, product_identity FROM bargain_searches WHERE id=?",
            (search_id,),
        ).fetchone()
        if row is None:
            return
        queries = json.loads(row[0])
        product_identity = row[1]
        conn.execute(
            "UPDATE bargain_searches SET status='running', listing_ids='[]' WHERE id=?",
            (search_id,),
        )
        conn.commit()
    finally:
        conn.close()

    queued: list[str] = []
    lock = threading.Lock()

    def run(name: str, mp: Marketplace) -> None:
        mconn = get_connection()
        try:
            for query in queries:
                page = 1
                while True:
                    try:
                        result = mp.search(query, page, location)
                    except Exception:
                        break  # this query/marketplace failed; keep the others
                    new_ids = _persist_and_triage(
                        mconn, result.listings, name, product_identity
                    )
                    with lock:
                        queued.extend(new_ids)
                        snapshot = json.dumps(queued)
                    mconn.execute(
                        "UPDATE bargain_searches SET listing_ids=? WHERE id=?",
                        (snapshot, search_id),
                    )
                    mconn.commit()
                    if page >= result.total_pages:
                        break
                    page += 1
        finally:
            mconn.close()

    threads = [threading.Thread(target=run, args=(n, m)) for n, m in marketplaces.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE bargain_searches SET status=? WHERE id=?",
            ("enriching" if queued else "complete", search_id),
        )
        conn.commit()
    finally:
        conn.close()


def _persist_and_triage(
    conn: sqlite3.Connection,
    listings: list[Listing],
    marketplace: str,
    product_identity: str,
) -> list[str]:
    """Store new listings; queue the ones triage calls match/unsure.

    Returns the listing ids that entered the enrichment queue.
    """
    queued: list[str] = []
    for listing in listings:
        listing.marketplace = marketplace
        lid = f"{marketplace}:{listing.id}"
        cur = conn.execute(
            "INSERT OR IGNORE INTO listings (id, raw) VALUES (?, ?)",
            (lid, json.dumps(vars(listing))),
        )
        if cur.rowcount == 0:
            continue  # already seen; not new
        summary = " ".join(x for x in (listing.title, listing.snippet) if x)
        try:
            verdict = router.triage(summary, product_identity)
        except Exception:
            verdict = "unsure"  # never silently drop on a triage error
        if verdict in ("match", "unsure"):
            conn.execute(
                "INSERT OR IGNORE INTO enrichments (listing_id, status) VALUES (?, 'pending')",
                (lid,),
            )
            queued.append(lid)
    return queued


def _refresh_progress(conn: sqlite3.Connection, search_id: int) -> None:
    """Flip an 'enriching' search to 'complete' once its queue has drained."""
    ids = json.loads(
        conn.execute(
            "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
        ).fetchone()[0]
    )
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    pending = conn.execute(
        f"SELECT COUNT(*) FROM enrichments "
        f"WHERE status='pending' AND listing_id IN ({placeholders})",
        ids,
    ).fetchone()[0]
    if pending == 0:
        conn.execute(
            "UPDATE bargain_searches SET status='complete' WHERE id=?", (search_id,)
        )
        conn.commit()


def _enrich_one(conn: sqlite3.Connection, marketplaces: dict[str, Marketplace], lid: str) -> None:
    """Enrich one listing: fetch detail, run the big model, write the record.

    Retries once on failure; a second failure marks the row 'failed'.
    """
    raw = conn.execute("SELECT raw FROM listings WHERE id=?", (lid,)).fetchone()
    if raw is None:
        conn.execute("UPDATE enrichments SET status='failed' WHERE listing_id=?", (lid,))
        conn.commit()
        return
    for attempt in range(2):
        try:
            listing = Listing(**json.loads(raw[0]))
            mp = marketplaces[listing.marketplace]
            detail = mp.fetch_detail(listing)
            text = f"{listing.title}\n\n{detail.description}"
            record = router.enrich(text)
            conn.execute(
                "UPDATE enrichments SET product=?, condition=?, bundle=?, confidence=?, "
                "model=?, status='enriched' WHERE listing_id=?",
                (
                    json.dumps(record["product"]),
                    record["condition"],
                    json.dumps(record["bundle"]),
                    json.dumps(record["confidence"]),
                    router.ENRICH_MODEL,
                    lid,
                ),
            )
            conn.commit()
            return
        except Exception:
            if attempt == 1:
                conn.execute(
                    "UPDATE enrichments SET status='failed' WHERE listing_id=?", (lid,)
                )
                conn.commit()


def enrichment_worker(
    marketplaces: dict[str, Marketplace],
    poll_seconds: float = 2.0,
) -> None:
    """Single-concurrency loop draining pending enrichment rows. Restart-resumable."""
    conn = get_connection()
    try:
        while True:
            row = conn.execute(
                "SELECT listing_id FROM enrichments WHERE status='pending' LIMIT 1"
            ).fetchone()
            if row is None:
                time.sleep(poll_seconds)
                continue
            _enrich_one(conn, marketplaces, row[0])
            for srow in conn.execute(
                "SELECT id FROM bargain_searches WHERE status='enriching'"
            ).fetchall():
                _refresh_progress(conn, srow[0])
    finally:
        conn.close()
