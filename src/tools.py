"""Chat tools: Listing Store keyword search (ticket #3); web search arrives in ticket #6.

search_listings queries what we already observed (the Listing Store), never a
live Marketplace. Output is compact plain text for the LLM context window:
one block per hit, raw fields plus an explicit enrichment status per hit.
"""

from __future__ import annotations

import json
import sqlite3
from src.db import get_connection

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
            resolved = " ".join(str(v) for v in product.values() if v)
            e_cond = r["e_condition"] or "?"
            status = f"Enriched: {resolved}, condition: {e_cond}"
        else:
            status = "not enriched"
        blocks.append(f"Title: {r['title']}\nPrice: {price}\nCondition: {condition}\nEnrichment: {status}")
    return "\n\n".join(blocks)
