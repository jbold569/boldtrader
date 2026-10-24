"""Bargain Search chat authoring: LLM conversation, draft contract, persistence.

The LLM clarifies the user's buying needs until it can state a product
identity, then proposes a draft Bargain Search as a fenced JSON block. The
user confirms or edits the draft on the confirmation screen; that creates
the `bargain_searches` row (or, on refinement, replaces the fields with a
version bump). The full transcript is persisted in `conversations`.
"""

from __future__ import annotations

import json
import re
import sqlite3

from .router import chat as llm_chat

SYSTEM_PROMPT = """You author BoldTrader Bargain Searches: durable buying intents \
for used computer hardware, fanned out as keyword searches across marketplaces.
Your job is translating the user's buying needs into keyword queries and filters.
You are a search translator, not a purchase advisor.

Conversation rules:
- Ask clarifying questions until you can state the product identity back to the
  user as one unambiguous phrase (e.g. "Dell OptiPlex micro PC, Core i5 8th
  gen"). Never present a draft before the product identity is settled.
- Once it is settled, present a draft: a one-line human-readable summary
  ("Core i5-8400 mini PCs, complete, <= $150"), the curated keyword queries,
  any exclusions, an optional target price, and the search location (city, state
  — ask the user where they want to search if they haven't said).
- Curate queries the way a human buyer searches: plain layperson terms plus
  model numbers, 3 to 8 queries, each a phrase a seller might have typed.
- Keep your visible reply short: at most a few sentences. Do NOT enumerate
  queries or exclusions as prose lists — the JSON block carries them.

When your reply contains a draft, end the reply with a fenced JSON block and no
prose after it, exactly this shape:

```json
{
  "summary": "<one-line summary>",
  "product_identity": "<the thing the user wants>",
  "queries": ["<keyword query>", "..."],
  "exclusions": ["<thing to exclude>", "..."],
  "target_price": <number or null>,
  "location": "<city, state>"
}
```
"""


class DraftError(ValueError):
    """A draft that violates the Bargain Search contract."""


_DRAFT_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def parse_reply(content: str) -> tuple[str, dict | None]:
    """Split an LLM reply into visible text and a validated draft.

    A missing or contract-violating draft is not an error: the reply renders
    as plain chat text and the conversation continues.
    """
    m = _DRAFT_RE.search(content)
    if m is None:
        return content, None
    try:
        draft = validate_draft(json.loads(m.group(1)))
    except (ValueError, DraftError):
        return content, None
    text = (content[: m.start()] + content[m.end():]).strip()
    return text, draft


def validate_draft(raw: dict) -> dict:
    """Enforce the draft contract; raise DraftError on any violation."""
    if not isinstance(raw, dict):
        raise DraftError("draft must be a JSON object")
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise DraftError("summary must be a non-empty string")
    identity = raw.get("product_identity")
    if not isinstance(identity, str) or not identity.strip():
        raise DraftError("product_identity must be a non-empty string")
    queries = raw.get("queries")
    if (
        not isinstance(queries, list)
        or not queries
        or not all(isinstance(q, str) and q.strip() for q in queries)
    ):
        raise DraftError("queries must be a non-empty list of strings")
    exclusions = raw.get("exclusions")
    if exclusions is None:
        exclusions = []
    if not isinstance(exclusions, list) or not all(
        isinstance(x, str) and x.strip() for x in exclusions
    ):
        raise DraftError("exclusions must be a list of strings")
    tp = raw.get("target_price")
    if tp is not None and (
        isinstance(tp, bool) or not isinstance(tp, (int, float)) or tp <= 0
    ):
        raise DraftError("target_price must be a positive number or null")
    return {
        "summary": summary.strip(),
        "product_identity": identity.strip(),
        "queries": [q.strip() for q in queries],
        "exclusions": [x.strip() for x in exclusions],
        "target_price": float(tp) if tp is not None else None,
        "location": (raw.get("location") or "Kenmore, WA").strip() or "Kenmore, WA",
    }


def draft_from_form(form: dict) -> dict:
    """Build a draft from the confirmation form (newline-separated list fields)."""

    def items(key: str) -> list[str]:
        # Newline-separated: keyword queries routinely contain commas.
        raw = (form.get(key) or [""])[0]
        return [s.strip() for s in raw.splitlines() if s.strip()]

    tp_raw = (form.get("target_price") or [""])[0].strip()
    tp: float | None = None
    if tp_raw:
        try:
            tp = float(tp_raw)
        except ValueError:
            raise DraftError(f"target_price {tp_raw!r} is not a number")
    return validate_draft(
        {
            "summary": (form.get("summary") or [""])[0],
            "product_identity": (form.get("product_identity") or [""])[0],
            "queries": items("queries"),
            "exclusions": items("exclusions"),
            "target_price": tp,
            "location": (form.get("location") or [""])[0],
        }
    )


def _system_for(search: dict | None) -> str:
    """System prompt; refinement turns get the current search state appended."""
    if search is None:
        return SYSTEM_PROMPT
    tp = search["target_price"]
    return (
        SYSTEM_PROMPT
        + "\nCurrent Bargain Search being refined: "
        f"summary={search['summary']!r}; "
        f"product_identity={search['product_identity']!r}; "
        f"queries={search['queries']!r}; "
        f"exclusions={search['exclusions']!r}; "
        f"target_price={tp if tp is not None else 'none'}; "
        f"location={search['location']!r}. "
        "The user is refining this search. When their new needs are clear, "
        "present a fresh full draft; confirming it replaces the search above."
    )


def next_reply(
    transcript: list[dict], user_message: str, search: dict | None = None
) -> tuple[str, dict | None]:
    """One authoring turn: system + transcript + new message in, (reply, draft) out."""
    messages = [{"role": "system", "content": _system_for(search)}]
    messages += [{"role": m["role"], "content": m["content"]} for m in transcript]
    messages.append({"role": "user", "content": user_message})
    return parse_reply(llm_chat(messages))


def create_search(conn: sqlite3.Connection, draft: dict) -> int:
    """Sign the contract: insert the confirmed draft as a new Bargain Search."""
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, location, target_price, queries, exclusions, listing_ids) "
        "VALUES (?, ?, ?, ?, ?, ?, '{}')",
        (
            draft["summary"],
            draft["product_identity"],
            draft["location"],
            draft["target_price"],
            json.dumps(draft["queries"]),
            json.dumps(draft["exclusions"]),
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_search(conn: sqlite3.Connection, search_id: int, draft: dict) -> None:
    """Refinement: replace the search fields and bump its version."""
    conn.execute(
        "UPDATE bargain_searches SET summary=?, product_identity=?, location=?, target_price=?, "
        "queries=?, exclusions=?, version=version+1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (
            draft["summary"],
            draft["product_identity"],
            draft["location"],
            draft["target_price"],
            json.dumps(draft["queries"]),
            json.dumps(draft["exclusions"]),
            search_id,
        ),
    )
    conn.commit()


def get_search(conn: sqlite3.Connection, search_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, summary, product_identity, location, target_price, queries, exclusions, version, status "
        "FROM bargain_searches WHERE id=?",
        (search_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "summary": row[1],
        "product_identity": row[2],
        "location": row[3],
        "target_price": row[4],
        "queries": json.loads(row[5]),
        "exclusions": json.loads(row[6]),
        "version": row[7],
        "status": row[8],
    }


def append_message(conn: sqlite3.Connection, search_id: int, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO conversations (bargain_search_id, role, content) VALUES (?, ?, ?)",
        (search_id, role, content),
    )
    conn.commit()


def load_transcript(conn: sqlite3.Connection, search_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM conversations WHERE bargain_search_id=? ORDER BY rowid",
        (search_id,),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


def delete_search(conn: sqlite3.Connection, search_id: int) -> None:
    """Delete a Bargain Search and its own rows.

    Listings and enrichments are shared across searches and stay; only the
    search's own records (search, transcript, rejects) are removed.
    """
    conn.execute("DELETE FROM rejects WHERE bargain_search_id=?", (search_id,))
    conn.execute("DELETE FROM conversations WHERE bargain_search_id=?", (search_id,))
    conn.execute("DELETE FROM bargain_searches WHERE id=?", (search_id,))
    conn.commit()
