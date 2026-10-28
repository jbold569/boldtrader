"""Fan-out + enrichment worker (ticket 05).

On confirmation, fan every curated query across all marketplaces (paginated,
tolerant of single-marketplace failure), persist each new listing, and sift it.
Listings judged match/unsure enter the enrichment queue. A single background
worker drains the queue: fetch_detail + enrich, retry once, then mark failed.
The queue is the database: status columns make it restart-resumable.

Search status flow: 'running' (fan-out in progress) -> 'enriching' (fan-out
done, enrichment pending) -> 'complete' (queue drained). Failed rows can be
re-queued later via reenrich_search (the ↻ Refresh button on each search card).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from . import events, router

from .db import get_connection
from .marketplace import Listing, Marketplace



log = logging.getLogger("boldtrader.fanout")

# Throttle: a dead network makes every fetch fail in ~300ms, so an unpaced
# drain of hundreds of rows becomes a request firehose that gets the host IP
# blocked by the marketplaces. Pace every outbound request and cool down hard
# on a burst of consecutive failures (the signature of an outage, not of a
# single bad listing).
ENRICH_MIN_INTERVAL_SECONDS = 5.0
ENRICH_RETRY_BACKOFF_SECONDS = 1.0
ENRICH_CONSECUTIVE_FAILURE_LIMIT = 5
ENRICH_COOLDOWN_SECONDS = 300.0

def fan_out(
    marketplaces: dict[str, Marketplace],
    search_id: int,
    location: str | None = None,
) -> None:
    """Run every query across every marketplace; persist + sift new listings.

    One thread per marketplace (same tolerance pattern as _search_all): a
    single marketplace failing is a note, not an error. Match/unsure listings
    are queued for enrichment and tracked in the search's listing_ids (the
    progress denominator).
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT queries, product_identity, exclusions FROM bargain_searches WHERE id=?",
            (search_id,),
        ).fetchone()
        if row is None:
            return
        queries = json.loads(row[0])
        product_identity = row[1]
        exclusions = json.loads(row[2])
        conn.execute(
            "UPDATE bargain_searches SET status='running', listing_ids='{}' WHERE id=?",
            (search_id,),
        )
        conn.commit()
    finally:
        conn.close()

    log.info(
        "fan-out #%s started: %d queries x %s @ %s",
        search_id, len(queries), list(marketplaces), location,
    )
    verdicts: dict[str, str] = {}
    lock = threading.Lock()

    def run(name: str, mp: Marketplace) -> None:
        mconn = get_connection()
        try:
            for query in queries:
                page = 1
                while True:
                    try:
                        result = mp.search(query, page, location)
                    except Exception as exc:
                        log.warning(
                            "fan-out #%s: %s query %r page %d failed: %s",
                            search_id, name, query, page, exc,
                        )
                        break  # this query/marketplace failed; keep the others
                    with lock:
                        known = set(verdicts)
                        new_verdicts = _persist_and_sift(
                        mconn, result.listings, name, product_identity, exclusions, known
                    )
                    with lock:
                        verdicts.update(new_verdicts)
                        snapshot = json.dumps(verdicts)
                    mconn.execute(
                        "UPDATE bargain_searches SET listing_ids=? WHERE id=?",
                        (snapshot, search_id),
                    )
                    mconn.commit()
                    if page >= result.total_pages:
                        break
                    page += 1
        except Exception:
            log.exception("fan-out #%s: %s crashed", search_id, name)
        finally:
            mconn.close()

    threads = [threading.Thread(target=run, args=(n, m)) for n, m in marketplaces.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = get_connection()
    try:
        queued_any = any(v in ("match", "unsure") for v in verdicts.values())
        conn.execute(
            "UPDATE bargain_searches SET status=? WHERE id=?",
            ("enriching" if queued_any else "complete", search_id),
        )
        conn.commit()
        log.info(
            "fan-out #%s done: %d listings, %s",
            search_id, len(verdicts), "enriching" if queued_any else "complete",
        )
        if not queued_any:
            # Nothing entered the enrichment queue, so the worker's drain
            # never flips this search; the completion happens right here.
            events.publish(
                "search_complete", {"search_id": search_id, "match_count": 0}
            )
    finally:
        conn.close()


def _persist_and_sift(
    conn: sqlite3.Connection,
    listings: list[Listing],
    marketplace: str,
    product_identity: str,
    exclusions: list[str],
    known_lids: set[str],
) -> dict[str, str]:
    """Store new listings; queue the ones the sift calls match/unsure.

    Returns {listing_id: verdict} for the new listings in this batch.
    Not-matches stay in the pass-through view but never enter the
    enhanced view.

    "Already seen" is per-search (known_lids), not global: a listing
    persisted by another search still needs sifting for this one. The
    listings table is a raw cache, not the dedup key.

    Three short write transactions with the slow sift calls in between:
    holding a SQLite write lock across LLM latency starves every other
    writer (the enrichment worker) and blows the busy timeout.
    """
    # Phase 1: persist new listings, find which are actually new.
    new_listings: list[tuple[str, str]] = []  # (lid, summary)
    for listing in listings:
        listing.marketplace = marketplace
        lid = f"{marketplace}:{listing.id}"
        conn.execute(
            "INSERT OR IGNORE INTO listings (id, raw) VALUES (?, ?)",
            (lid, json.dumps(vars(listing))),
        )
        if lid in known_lids:
            continue  # already sifted for this search
        summary = " ".join(x for x in (listing.title, listing.snippet) if x)
        new_listings.append((lid, summary))
    conn.commit()

    # Phase 2: sift outside any transaction (slow, no lock held).
    verdicts: dict[str, str] = {}
    for lid, summary in new_listings:
        try:
            verdict = router.sift(summary, product_identity, exclusions=exclusions)
        except Exception as exc:
            log.warning("sift failed for %s: %s (marking unsure)", lid, exc)
            verdict = "unsure"  # never silently drop on a sift error
        verdicts[lid] = verdict

    # Phase 3: queue match/unsure for enrichment.
    for lid, verdict in verdicts.items():
        if verdict in ("match", "unsure"):
            conn.execute(
                "INSERT OR IGNORE INTO enrichments (listing_id, status) VALUES (?, 'pending')",
                (lid,),
            )
    conn.commit()
    return verdicts


def _refresh_progress(conn: sqlite3.Connection, search_id: int) -> None:
    """Flip an 'enriching' search to 'complete' once its queue has drained."""
    row = conn.execute(
        "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    if row is None:
        return  # search was deleted mid-flight
    verdicts = json.loads(row[0])
    if not verdicts:
        return
    ids = list(verdicts)
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
        log.info("search #%s complete", search_id)
        events.publish(
            "search_complete",
            {
                "search_id": search_id,
                "match_count": sum(1 for v in verdicts.values() if v in ("match", "unsure")),
            },
        )


def reenrich_search(conn: sqlite3.Connection, search_id: int) -> int:
    """Re-queue a search's listings for Enrichment; returns how many were queued.

    Targets match/unsure listings whose enrichment is missing or failed;
    already-enriched rows are left untouched. Re-enrichment re-reads the
    listing from the Marketplace, so the re-queue reflects current data.
    Idempotent: safe to call repeatedly, even mid-drain.
    """
    row = conn.execute(
        "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    if row is None:
        return 0
    verdicts = json.loads(row[0])
    ids = [lid for lid, v in verdicts.items() if v in ("match", "unsure")]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    queued_missing = conn.execute(
        f"INSERT OR IGNORE INTO enrichments (listing_id, status) "
        f"SELECT id, 'pending' FROM listings WHERE id IN ({placeholders}) "
        "AND id NOT IN (SELECT listing_id FROM enrichments)",
        ids,
    ).rowcount
    failed = conn.execute(
        f"UPDATE enrichments SET status='pending' "
        f"WHERE status='failed' AND listing_id IN ({placeholders})",
        ids,
    ).rowcount
    total = queued_missing + failed
    if total:
        conn.execute(
            "UPDATE bargain_searches SET status='enriching' WHERE id=?",
            (search_id,),
        )
    conn.commit()
    return total


def _enrich_one(conn: sqlite3.Connection, marketplaces: dict[str, Marketplace], lid: str) -> bool:
    """Enrich one listing: fetch detail, run the big model, write the record.

    Retries once (after a short backoff) on failure; a second failure marks
    the row 'failed'. Returns True on success, False on permanent failure.
    """
    row = conn.execute("SELECT raw, authored_description FROM listings WHERE id=?", (lid,)).fetchone()
    if row is None:
        conn.execute("UPDATE enrichments SET status='failed' WHERE listing_id=?", (lid,))
        conn.commit()
        events.publish("enrichment", {"listing_id": lid, "status": "failed"})
        return False
    raw, authored = row[0], row[1] or ""
    for attempt in range(2):
        try:
            listing = Listing(**json.loads(raw))
            mp = marketplaces[listing.marketplace]
            detail = mp.fetch_detail(listing)
            text = f"{listing.title}\n\n{detail.description}"
            record = router.enrich(text, authored=authored)
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
            log.info("enriched %s", lid)
            events.publish("enrichment", {"listing_id": lid, "status": "enriched"})
            return True
        except Exception as exc:
            log.warning("enrich attempt %d failed for %s: %s", attempt + 1, lid, exc)
            if attempt == 0:
                time.sleep(ENRICH_RETRY_BACKOFF_SECONDS)
    conn.execute(
        "UPDATE enrichments SET status='failed' WHERE listing_id=?", (lid,)
    )
    conn.commit()
    log.warning("enrichment failed permanently for %s", lid)
    events.publish("enrichment", {"listing_id": lid, "status": "failed"})
    return False


def enrichment_worker(
    marketplaces: dict[str, Marketplace],
    poll_seconds: float = 2.0,
) -> None:
    """Single-concurrency loop draining pending enrichment rows. Restart-resumable.

    Throttle: at most one enrichment per ENRICH_MIN_INTERVAL_SECONDS (the
    interval covers the whole row: fetch_detail + model call + DB write; if
    the work already took longer, no extra wait). A run of
    ENRICH_CONSECUTIVE_FAILURE_LIMIT consecutive failures is treated as an
    outage (dead DNS/network, blocked IP) rather than bad listings, so the
    worker backs off ENRICH_COOLDOWN_SECONDS instead of firehosing the
    upstream and getting the host shut down.
    """
    conn = get_connection()
    log.info("enrichment worker started")
    try:
        next_allowed = 0.0
        consecutive_failures = 0
        while True:
            row = conn.execute(
                "SELECT listing_id FROM enrichments WHERE status='pending' LIMIT 1"
            ).fetchone()
            if row is None:
                time.sleep(poll_seconds)
                continue
            wait = next_allowed - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            ok = _enrich_one(conn, marketplaces, row[0])
            next_allowed = time.monotonic() + ENRICH_MIN_INTERVAL_SECONDS
            if ok:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= ENRICH_CONSECUTIVE_FAILURE_LIMIT:
                    log.warning(
                        "%d consecutive enrichment failures; cooling down %.0fs "
                        "(upstream outage?)",
                        consecutive_failures, ENRICH_COOLDOWN_SECONDS,
                    )
                    time.sleep(ENRICH_COOLDOWN_SECONDS)
                    consecutive_failures = 0
            for srow in conn.execute(
                "SELECT id FROM bargain_searches WHERE status='enriching'"
            ).fetchall():
                _refresh_progress(conn, srow[0])
    except Exception:
        log.exception("enrichment worker crashed; queue left for the next start")
        raise
