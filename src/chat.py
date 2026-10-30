"""Chat Session core: LLM conversation, draft contract, persistence.

A Chat Session is a general-purpose conversation (research, analysis,
buying help). When a Bargain Search draft is ready, the LLM proposes it
as a fenced JSON block; the user confirms or edits it on the
confirmation screen, which creates the `bargain_searches` row. The full
transcript is persisted on the session (`chat_sessions` +
`session_messages`).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from .db import get_connection

from . import identity, router
from .tools import get_listing, search_listings, web_search

# The four chat tools (tickets #6, #10, #11; ADR 0007): product identification
# (what BoldTrader has already seen, live lookups, the full stored record of
# one Listing) plus deleting a named Bargain Search (ticket #11).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_listings",
            "description": (
                "Search what BoldTrader has already seen: a keyword search "
                "over stored listings. Use it to check whether we have "
                "already seen a product or what it looked like. One short "
                "keyword string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Short keyword: a model number or product phrase.",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for prices and product information. "
                "Use it to identify the product the user wants and what it "
                "typically costs. One short query string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Short web search query.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_listing",
            "description": (
                "Get the full stored record of one Listing from the "
                "Listing Store by its Listing ID: raw marketplace "
                "fields, Enrichment, authored description, and "
                "availability. Store only; never a live marketplace "
                "fetch. One listing id string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "The Listing ID (marketplace listing id).",
                    }
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_bargain_search",
            "description": (
                "Delete one Bargain Search and its own rows by its id. "
                "Only call this when the user's own message explicitly "
                "named that specific search (its id number or its exact "
                "summary). Never delete on vague or blanket requests. One "
                "search id string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "The Bargain Search id to delete.",
                    }
                },
                "required": ["id"],
            },
        },
    },
]

# Maximum tool rounds per turn (ADR 0007, raised to 6 per ticket #10); the
# next call is made without tools so the model must answer.
MAX_TOOL_ROUNDS = 6

# Search tools join result blocks with a blank line, and every block starts
# with the tool's own marker: "1. " (web) / "Title: " (store). get_listing
# returns a single "Listing: " block.
_RESULT_BLOCK_RE = re.compile(r"^(?:\d+\. |Title: )")

SYSTEM_PROMPT = """You are the BoldTrader research and buying assistant: a \
general-purpose agent for used computer hardware. You help the user research \
products, analyze listings, and manage Bargain Searches.

Analysis rules:
- You may analyze deals and give your opinion: state the math out loud (asking \
price, shipping, flip value of unwanted extras, effective price) and state \
your fair-price confidence (high/medium/low) for any number you give.
- Never invent facts beyond what your tools return. If a lookup did not answer \
the question, say so plainly instead of guessing.
- Never urge the user to buy. Present the analysis; the decision is always \
the user's. Do not manufacture urgency, scarcity, or pressure.

Bargain Search drafts:
- When the user wants a new Bargain Search, ask clarifying questions until \
you can state the product identity back to them as one unambiguous phrase \
(e.g. "Dell OptiPlex micro PC, Core i5 8th gen"). Never present a draft \
before the product identity is settled.
- Once it is settled, present the draft — and ONLY by emitting the fenced
  JSON block shown at the bottom of these rules. A draft that is not
  inside a fenced json block does not exist. The web UI turns each fenced
  block into a confirmation form, and that form is the only way a Bargain
  Search gets created: prose that describes a search creates nothing.
- The draft needs: a one-line human-readable summary ("Core i5-8400 mini
  PCs, complete, <= $150"), curated keyword queries, any exclusions, an
  optional target price, and the search location (city, state — ask the
  user where they want to search if they haven't said).
- Curate queries the way a human buyer searches: plain layperson terms
  plus model numbers, 3 to 8 queries, each a phrase a seller might have
  typed.
- Keep your visible reply short: at most a few sentences. Do NOT
  enumerate queries, exclusions or any other draft field as a prose
  list — the JSON block carries them and the confirmation form displays
  them.

- You have four tools: search_listings (keyword search over what
  BoldTrader has already seen), web_search (live prices and product
  info), get_listing (the full stored record of one Listing by its
  Listing ID — raw fields, Enrichment, authored description,
  availability; Listing Store only, never a live fetch), and
  delete_bargain_search (delete one Bargain Search by its id). Use the
  lookup tools to ground your answers: check typical prices, whether we
  have already seen an item, and pull the full record when the user
  points at a specific listing. One or two targeted lookups per
  question; never browse endlessly.
- delete_bargain_search rule: only call it when the user's own message
  explicitly named the specific search to delete — by its id number or
  its exact summary. If the request is ambiguous ("clean up some of my
  searches", "delete an old one") or names no target, refuse and ask
  which specific search they mean. There is no bulk delete.

Every reply that proposes one or more Bargain Searches MUST end with one
fenced JSON block per proposed search, back to back, with no prose after
the last block. No fenced block means nothing was proposed. The shape:

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

_DRAFT_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

_XML_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=[^>]*>.*?</function>\s*</tool_call>", re.DOTALL
)


def strip_tool_call_text(content: str) -> str:
    """Remove ChatML tool-call XML from model text.

    The router occasionally emits a tool call as ChatML/XML text instead of
    structured deltas. Handles complete blocks, a block cut off mid-stream
    (truncate at the dangling opener), and stray im_end/im_start markers.
    """
    out = _XML_TOOL_CALL_RE.sub("", content)
    dangling = out.find("<tool_call>")
    if dangling != -1:
        out = out[:dangling]
    out = out.replace("<|im_end|>", "").replace("<|im_start|>", "")
    return out.strip()


def parse_reply(content: str) -> tuple[str, list[dict]]:
    """Split an LLM reply into visible text and the list of proposed drafts.

    ChatML tool-call text is stripped first: it is model plumbing, not
    prose. The model may propose several Bargain Searches in one reply,
    each in its own fenced JSON block; one confirmation form renders per
    draft. A contract-violating block is not an error: it is skipped (and
    stays visible in the text) while the valid ones still count.
    """
    text = strip_tool_call_text(content)
    if text != content.strip():
        logging.getLogger(__name__).warning(
            "model emitted raw ChatML tool-call text; stripped. raw=%r", content
        )

    drafts: list[dict] = []

    def _collect(m: re.Match) -> str:
        try:
            drafts.append(validate_draft(json.loads(m.group(1))))
        except (ValueError, DraftError):
            return m.group(0)
        return ""

    text = _DRAFT_RE.sub(_collect, text).strip()
    return text, drafts


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


def chip_text(tool_name: str, query: str, output: str) -> str:
    """One-line chip label for a stored tool result.

    The hit count is derivable when every blank-line-separated block of
    the tool output starts with the tool's own result marker ("1. " for
    web results, "Title: " for store hits); an empty output or an error
    string ("web search unavailable") yields name + query only.
    """
    if not query:
        return tool_name
    if output.startswith("No results"):
        return f'{tool_name}: "{query}" — no results'
    blocks = [b for b in output.split("\n\n") if b.strip()]
    if blocks and all(_RESULT_BLOCK_RE.match(b) for b in blocks):
        return f'{tool_name}: "{query}" — {len(blocks)} results'
    return f'{tool_name}: "{query}"'


def reconstruct_messages(rows: list[dict]) -> list[dict]:
    """Replay stored conversation rows into OpenAI chat messages.

    Assistant rows holding a tool-call JSON blob come back with
    tool_calls intact; each following role="tool" row maps, in order, to
    the corresponding tool call's id. Plain rows pass through unchanged.
    """
    messages: list[dict] = []
    pending: list[str] = []  # tool_call ids awaiting their result row
    for row in rows:
        role = row["role"]
        content = row["content"]
        if role == "tool":
            tool_call_id = pending.pop(0) if pending else ""
            messages.append(
                {"role": "tool", "tool_call_id": tool_call_id, "content": content}
            )
            continue
        if role == "assistant":
            try:
                data = json.loads(content)
            except (ValueError, TypeError):
                data = None
            if isinstance(data, dict) and data.get("tool_calls"):
                for call in data["tool_calls"]:
                    pending.append(call.get("id", ""))
                messages.append(
                    {
                        "role": "assistant",
                        "content": data.get("content", ""),
                        "tool_calls": data["tool_calls"],
                    }
                )
                continue
        messages.append({"role": role, "content": content})
    return messages


def _run_tool(call: dict, conn: sqlite3.Connection, user_message: str) -> tuple[str, str, str]:
    """Execute one tool call; never raises — failures become tool output.

    delete_bargain_search is checked against the latest user message here
    (see handle_delete_bargain_search); the other tools stand alone.
    """
    name = call.get("function", {}).get("name", "")
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
    except (ValueError, TypeError):
        args = {}
    if name == "delete_bargain_search":
        query = str(args.get("id", ""))
        try:
            return name, query, handle_delete_bargain_search(conn, query, user_message)
        except Exception as exc:
            return name, query, f"tool error: {exc}"
    fn = {
        "search_listings": search_listings,
        "web_search": web_search,
        "get_listing": get_listing,
    }.get(name)
    if fn is None:
        return name, "", f"tool error: unknown tool {name!r}"
    try:
        output = fn(**args)
    except Exception as exc:  # tool blow-ups flow back to the model as output
        query = next(iter(args.values()), "") if args else ""
        return name, query, f"tool error: {exc}"
    query = next(iter(args.values()), "") if args else ""
    return name, query, output


def next_reply(
    transcript: list[dict],
    user_message: str,
    conn: sqlite3.Connection | None = None,
    session_id: int | None = None,
) -> tuple[str, list[dict], list[dict]]:
    """One chat turn with tool use (ticket #8, ADR 0008).

    Returns ``(reply, drafts, turn_rows)`` where drafts are the validated
    Bargain Search drafts proposed this turn (possibly several, one per
    search) and turn_rows are this turn's
    assistant message (stored as JSON so tool_calls survive) plus one
    role="tool" row per call, then the final assistant row. Pass conn and
    session_id to persist each row on the Chat Session as it is produced;
    the user message is saved before the first model call, so it survives
    even if that call fails. Omit conn/session_id for a dry run.

    At most MAX_TOOL_ROUNDS tool rounds; the call after that is made
    without tools so the model must answer.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += reconstruct_messages(transcript)
    messages.append({"role": "user", "content": user_message})
    turn_rows: list[dict] = []

    def emit(row: dict) -> None:
        turn_rows.append(row)
        if conn is not None and session_id is not None:
            append_session_message(conn, session_id, row["role"], row["content"])
            _touch(conn, session_id)

    emit({"role": "user", "content": user_message})

    for _ in range(MAX_TOOL_ROUNDS):
        msg = router.chat_with_tools(messages, tools=TOOL_SCHEMAS)
        tool_calls = msg.get("tool_calls")
        text = msg.get("content") or ""
        if not tool_calls:
            reply, drafts = parse_reply(text)
            emit({"role": "assistant", "content": reply})
            return reply, drafts, turn_rows
        blob = json.dumps({"content": text, "tool_calls": tool_calls})
        messages.append(
            {
                "role": "assistant",
                "content": text,
                "tool_calls": tool_calls,
            }
        )
        emit({"role": "assistant", "content": blob})
        for call in tool_calls:
            name, query, output = _run_tool(call, conn, user_message)
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": output}
            )
            emit({"role": "tool", "content": output})

    # Round cap reached: ask once more without tools — the model must answer.
    msg = router.chat_with_tools(messages)
    text = msg.get("content") or ""
    reply, drafts = parse_reply(text)
    emit({"role": "assistant", "content": reply})
    return reply, drafts, turn_rows


def _touch(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE chat_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (session_id,)
    )
    conn.commit()


def create_search(conn: sqlite3.Connection, draft: dict) -> int:
    """Sign the contract: insert the confirmed draft as a new Bargain Search.

    The draft's product_identity phrase seeds a fresh Product Identity row
    (ticket #55, ADR 0012); the identity's living description is written
    from evidence at search_complete, not carried by the phrase."""
    identity_id = identity.seed_identity(conn, draft["product_identity"])
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, location, target_price, queries, exclusions, listing_ids, product_identity_id) "
        "VALUES (?, ?, ?, ?, ?, ?, '{}', ?)",
        (
            draft["summary"],
            draft["product_identity"],
            draft["location"],
            draft["target_price"],
            json.dumps(draft["queries"]),
            json.dumps(draft["exclusions"]),
            identity_id,
        ),
    )
    conn.commit()
    return cur.lastrowid



def update_search(conn: sqlite3.Connection, search_id: int, draft: dict) -> None:
    """Replace a Bargain Search's fields and bump its version."""
    conn.execute(
        "UPDATE bargain_searches SET summary=?, product_identity=?, target_price=?, "
        "location=?, queries=?, exclusions=?, version=version+1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (
            draft["summary"],
            draft["product_identity"],
            draft["target_price"],
            draft["location"],
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



def delete_search(conn: sqlite3.Connection, search_id: int) -> None:
    """Delete a Bargain Search and its own rows.

    Listings and enrichments are shared across searches and stay; only the
    search's own records (search, rejects) are removed.
    """
    conn.execute("DELETE FROM rejects WHERE bargain_search_id=?", (search_id,))
    conn.execute("DELETE FROM bargain_searches WHERE id=?", (search_id,))
    conn.commit()


# --- Chat Sessions (ticket #8, ADR 0008) -------------------------------------

def create_session(conn: sqlite3.Connection, title: str) -> int:
    cur = conn.execute("INSERT INTO chat_sessions (title) VALUES (?)", (title,))
    conn.commit()
    return cur.lastrowid


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, title FROM chat_sessions WHERE id=?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "title": row[1]}


def latest_session(conn: sqlite3.Connection) -> dict | None:
    """The most recently created session, or None if there are none."""
    row = conn.execute(
        "SELECT id, title FROM chat_sessions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "title": row[1]}


def append_session_message(
    conn: sqlite3.Connection, session_id: int, role: str, content: str
) -> None:
    conn.execute(
        "INSERT INTO session_messages (chat_session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content),
    )
    conn.commit()


def load_session_transcript(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM session_messages WHERE chat_session_id=? ORDER BY rowid",
        (session_id,),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


_TITLE_PROMPT = (
    "Write a short title (3 to 6 words) that names what this message is "
    "about. Reply with the title only — no quotes, no punctuation at the end.\n\n"
)


def generate_title(message: str) -> str:
    """Short session title from the first user message; 40-char fallback.

    One small LLM call. Any failure (router error, empty/whitespace reply)
    falls back to the first 40 characters of the message itself.
    """
    try:
        raw = router.chat(
            [{"role": "user", "content": _TITLE_PROMPT + message}], max_tokens=40
        )
    except Exception:
        raw = ""
    title = (raw or "").strip().strip('"').strip("'").strip()
    if not title:
        return message[:40]
    return title


def handle_delete_bargain_search(conn: sqlite3.Connection, id: str, user_message: str) -> str:
    """Delete one named Bargain Search; refuse unless the user named it.

    The explicit-naming check is a deliberately conservative mechanical
    test, not NLP: the latest user message must contain the search id as
    a whole number (\\b so 2 never matches inside 22) or the search's
    exact summary string. Anything else (vague, blanket, or unnamed
    requests) is refused and nothing is deleted.
    """
    raw = (id or "").strip()
    if not raw.isdigit():
        return f"Invalid search id {id!r}: expected a number."
    search_id = int(raw)
    search = get_search(conn, search_id)
    if search is None:
        return f"Bargain search #{search_id} not found."
    named = re.search(rf"\b{search_id}\b", user_message) or (
        search["summary"] and search["summary"] in user_message
    )
    if not named:
        return "Refused: the user did not explicitly name this search for deletion."
    delete_search(conn, search_id)
    return f'Deleted bargain search #{search_id}: "{search["summary"]}"'


