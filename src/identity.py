"""Product Identity lifecycle: seed, synthesize, retune (ticket #55, ADR 0012).

A Product Identity starts as the user's seed phrase and becomes a living
prose description: the first completed search synthesizes one from the
matched listings, every subsequent completion retunes it with the new
evidence (rejects, corrections, the deal threshold). The description is
what sift judges against from then on, so a change to it makes every
existing verdict stale — flagged, never silently re-sifted (ADR 0006:
re-sifting happens only on an explicit re-run).

Synthesis failures are silent by design: the identity keeps its previous
description and the next completion retries. A wrong description degrades
results gradually; a crash would stop the pipeline.
"""

from __future__ import annotations

import datetime
import json
import sqlite3

from . import router


def seed_identity(conn: sqlite3.Connection, phrase: str) -> int:
    """Create the identity row from the user's phrase; NULL synthesized_at
    marks it as a seed, not yet a synthesis."""
    cur = conn.execute(
        "INSERT INTO product_identities (description) VALUES (?)", (phrase,)
    )
    return cur.lastrowid


def _now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _rows_context(rows) -> list[dict]:
    """Turn (raw, authored_description, product_json) rows into clean
    evidence dicts: the listing title, the enriched product description,
    and any human-authored description."""
    context = []
    for raw, authored, product_json in rows:
        title = ""
        if raw:
            try:
                title = (json.loads(raw).get("title") or "").strip()
            except (ValueError, AttributeError):
                title = ""
        product = None
        if product_json:
            try:
                product = (json.loads(product_json).get("description") or "").strip() or None
            except (ValueError, AttributeError):
                product = None
        context.append(
            {
                "title": title,
                "product": product,
                "authored": (authored or "").strip() or None,
            }
        )
    return context


def _all_lids(conn: sqlite3.Connection, search_id: int) -> list[str]:
    row = conn.execute(
        "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    return list(json.loads(row[0])) if row and row[0] else []


def matched_lids(conn: sqlite3.Connection, search_id: int) -> list[str]:
    """The search's match/unsure lids minus the ones the user rejected:
    the reject is the user saying 'this is not the product', so it is
    counter-evidence, not raw material for the description."""
    lids = [
        lid
        for lid, v in _verdict_map(conn, search_id).items()
        if v in ("match", "unsure")
    ]
    if not lids:
        return []
    rejected = {
        r[0]
        for r in conn.execute(
            "SELECT listing_id FROM rejects WHERE bargain_search_id=?", (search_id,)
        )
    }
    return [lid for lid in lids if lid not in rejected]


def _verdict_map(conn: sqlite3.Connection, search_id: int) -> dict:
    row = conn.execute(
        "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def collect_matched_context(conn: sqlite3.Connection, search_id: int) -> list[dict]:
    """The matched listing context: what the match/unsure listings actually
    are, per their own titles and enriched product descriptions."""
    lids = matched_lids(conn, search_id)
    if not lids:
        return []
    placeholders = ",".join("?" * len(lids))
    rows = conn.execute(
        f"SELECT l.raw, l.authored_description, e.product "
        f"FROM listings l LEFT JOIN enrichments e ON e.listing_id = l.id "
        f"WHERE l.id IN ({placeholders})",
        lids,
    ).fetchall()
    return _rows_context(rows)


def _dedupe(items: list[dict]) -> list[dict]:
    """Union of reasons, not one row per listing: fifty rejects saying
    'too expensive' are one piece of advice, and repeating it would let
    the model weight it by volume."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = it["reason"].casefold()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _reject_evidence(conn: sqlite3.Connection, search_id: int) -> list[dict]:
    """Rejected listings for this search as {title, reason}."""
    rows = conn.execute(
        "SELECT r.reason, l.raw FROM rejects r "
        "LEFT JOIN listings l ON l.id = r.listing_id "
        "WHERE r.bargain_search_id=?",
        (search_id,),
    ).fetchall()
    items = []
    for reason, raw in rows:
        title = ""
        if raw:
            try:
                title = (json.loads(raw).get("title") or "").strip()
            except (ValueError, AttributeError):
                title = ""
        items.append({"title": title, "reason": (reason or "").strip()})
    return _dedupe(items)


def _authored_evidence(conn: sqlite3.Connection, search_id: int) -> list[str]:
    """The user's authored corrections across every listing this search
    saw — match or reject. An authored description on a rejected listing
    is the user spelling out what was wrong."""
    lids = _all_lids(conn, search_id)
    if not lids:
        return []
    placeholders = ",".join("?" * len(lids))
    rows = conn.execute(
        f"SELECT authored_description FROM listings WHERE id IN ({placeholders})",
        lids,
    ).fetchall()
    return [(a or "").strip() for (a,) in rows if (a or "").strip()]


def collect_retune_evidence(conn: sqlite3.Connection, search_id: int) -> dict:
    """Everything accumulated since the last synthesis: rejects, matched
    context, the user's authored corrections, and the current deal
    threshold (an edit to it is evidence the user disagrees with this
    identity's price band)."""
    threshold_row = conn.execute(
        "SELECT p.deal_threshold FROM bargain_searches s "
        "JOIN product_identities p ON p.id = s.product_identity_id "
        "WHERE s.id=?",
        (search_id,),
    ).fetchone()
    return {
        "mode": "retune",
        "matched": collect_matched_context(conn, search_id),
        "rejects": _reject_evidence(conn, search_id),
        "authored_descriptions": _authored_evidence(conn, search_id),
        "deal_threshold": threshold_row[0] if threshold_row else None,
    }


def update_identity_from_search(conn: sqlite3.Connection, search_id: int) -> None:
    """Ride the search_complete transition: synthesize (first completion)
    or retune (every later one) the identity's living description, and
    flag the now-stale verdicts on the search (ticket #55, ADR 0012)."""
    row = conn.execute(
        "SELECT p.description, p.synthesized_at FROM bargain_searches s "
        "JOIN product_identities p ON p.id = s.product_identity_id "
        "WHERE s.id=?",
        (search_id,),
    ).fetchone()
    if row is None:
        return  # search has no mapped identity (pre-T1 row)
    current_description, synthesized_at = row
    matched = collect_matched_context(conn, search_id)
    if not matched:
        return  # nothing new to learn from
    if synthesized_at is None:
        evidence = {
            "mode": "synthesize",
            "current_description": current_description,
            "matched": matched,
            "rejects": [],
            "authored_descriptions": [],
            "deal_threshold": None,
        }
    else:
        evidence = collect_retune_evidence(conn, search_id)
        evidence["current_description"] = current_description
    try:
        new_description = router.synthesize_description(evidence)
    except Exception:
        conn.rollback()
        return
    if not new_description.strip() or new_description == current_description:
        return
    now = _now()
    conn.execute(
        "UPDATE product_identities SET description=?, synthesized_at=?, updated_at=? "
        "WHERE id=(SELECT product_identity_id FROM bargain_searches WHERE id=?)",
        (new_description, now, now, search_id),
    )
    conn.execute(
        "UPDATE bargain_searches SET stale_lids=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(matched_lids(conn, search_id)), search_id),
    )
    conn.commit()
