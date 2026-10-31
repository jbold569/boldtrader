"""Chat tools: Listing Store keyword search (ticket #3) and web search (ticket #4).

search_listings queries what we already observed (the Listing Store), never a
live Marketplace. web_search queries live DuckDuckGo (organic results only,
per ADR 0007). Output is compact plain text for the LLM context window:
one block per hit.
"""

from __future__ import annotations

import json
import sqlite3
from src.db import get_connection
from ddgs import DDGS

# shortcut: revisit FTS5 past ~50k listings or when keyword search shows in a profile
# (LIKE over 608 rows scans in 0.2 ms; FTS5's default tokenizer mangles hyphenated
# model numbers like i5-8400, so it is rejected for now — see ADR 0007.)
_SQL = """
    SELECT json_extract(raw, '$.title')  AS title,
           json_extract(raw, '$.price')  AS price,
           json_extract(raw, '$.condition') AS condition,
           e.product     AS product,
           e.condition   e_condition,
           e.status      AS e_status
    FROM listings l
    LEFT JOIN enrichments e ON e.listing_id = l.id
    WHERE raw LIKE ? ESCAPE '\\'
    LIMIT 5
"""


def _desc(product: dict) -> str:
    """Description from a stored product record, legacy shapes included.

    Pre-#53 corpora stored {manufacturer, model, config} with no
    'description'; compose one instead of crashing.
    """
    d = (product.get("description") or "").strip()
    if d:
        return d
    parts = [product.get("manufacturer"), product.get("model")]
    return " ".join(p for p in parts if p and p.lower() != "unknown") or "unknown product"


def search_listings(keyword: str) -> str:
    """Top-5 case-insensitive substring search over listing title and raw text."""
    if not keyword or not keyword.strip():
        return "Keyword required."
    term = keyword.strip()
    escaped = (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(_SQL, (f"%{escaped}%",)).fetchall()
    finally:
        conn.close()
    if not rows:
        return f"No results for \"{keyword.strip()}\"."
    blocks = []
    for r in rows:
        price = r["price"] if r["price"] is not None else "?"
        condition = r["condition"] if r["condition"] else "?"
        if r["e_status"] == "enriched" and r["product"]:
            product = json.loads(r["product"])
            e_cond = r["e_condition"] or "?"
            status = f"Enriched: {_desc(product)}, condition: {e_cond}"
        else:
            status = "not enriched"
        blocks.append(f"Title: {r['title']}\nPrice: {price}\nCondition: {condition}\nEnrichment: {status}")
    return "\n\n".join(blocks)


def get_listing(id: str) -> str:
    """Full stored record of one Listing: raw fields, Enrichment,
    authored description, availability (ticket #10).

    Listing Store only — never a live Marketplace fetch. An id we have
    never seen returns an explicit "not seen" string.
    """
    if not id or not id.strip():
        return "Listing id required."
    lid = id.strip()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT l.raw, l.authored_description, l.availability, "
            "e.product, e.condition, e.bundle, e.confidence, e.status "
            "FROM listings l LEFT JOIN enrichments e ON e.listing_id = l.id "
            "WHERE l.id = ?",
            (lid,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return f'Listing "{lid}" not seen.'
    lines = [f"Listing: {lid}"]
    for key, value in json.loads(row["raw"]).items():
        lines.append(f"{key}: {value}")
    lines.append(f"Authored description: {row['authored_description'] or 'none'}")
    lines.append(f"Availability: {row['availability'] or 'live'}")
    if row["status"] == "enriched" and row["product"]:
        product = json.loads(row["product"])
        bundle_items = json.loads(row["bundle"]) if row["bundle"] else []
        bundle = (
            ", ".join(
                b if isinstance(b, str) else b.get("description", "")
                for b in bundle_items
            )
            or "none"
        )
        lines.append(
            f"Enrichment: {_desc(product)}, condition: {row['condition']}, "
            f"bundle: {bundle}, confidence: {product.get('confidence', '?')}"
        )
    else:
        lines.append("Enrichment: none")
    return "\n".join(lines)


def web_search(query: str) -> str:
    """Top-3 organic DuckDuckGo results as compact text (ADR 0007).

    Degrades to a plain string on every failure path: the chat turn must
    continue without web context rather than crash.
    """
    if not query or not query.strip():
        return "Query required."
    term = query.strip()
    try:
        results = DDGS().text(term, max_results=3, backend="html")
    except Exception:
        # ddgs raises a zoo of types (rate limit, timeout, network, parse);
        # all mean the same thing here: no web context this turn.
        return "web search unavailable"
    if not results:
        return f'No results for "{term}".'
    blocks = []
    for i, r in enumerate(results[:3], 1):
        title = r.get("title") or "?"
        url = r.get("href") or "?"
        snippet = r.get("body") or "?"
        blocks.append(f"{i}. {title}\nURL: {url}\nSnippet: {snippet}")
    return "\n\n".join(blocks)
