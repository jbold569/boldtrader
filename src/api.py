"""Bargain Search JSON API (tickets #38, #39) — the `/api/v1/searches` surface.

Additive over the existing chat/search persistence: list, create, partial
update, delete per docs/api-contract.md; the per-search results list with
server-side verdict/max_price/availability filters and sort applied before
pagination, plus the rejections, reenrichment, and liveness actions.
snake_case in and out, ISO 8601 timestamps, JSON error bodies on every
non-2xx. Create and update kick fan-out in a background thread after the
response is on the wire, exactly as the legacy /confirm and /search paths do.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from urllib.parse import parse_qs, urlparse

from . import chat as chat_mod
from . import enhanced, events, liveness
from .db import get_connection
from .fanout import fan_out, reenrich_search
from . import router

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200

SEARCH_COLUMNS = (
    "id, summary, product_identity, target_price, location, queries, "
    "exclusions, version, status, listing_ids, created_at, updated_at"
)

DRAFT_FIELDS = (
    "summary",
    "product_identity",
    "queries",
    "exclusions",
    "target_price",
    "location",
)


class ApiError(Exception):
    """A request the API refuses, with its HTTP status and error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --- Serialization -----------------------------------------------------------


def _iso(ts: str) -> str:
    """SQLite's 'YYYY-MM-DD HH:MM:SS' (UTC) to ISO 8601 with an explicit Z."""
    return ts.replace(" ", "T") + "Z"


def _match_count(listing_ids_json: str) -> int:
    verdicts = json.loads(listing_ids_json)
    return sum(1 for v in verdicts.values() if v in ("match", "unsure"))


def _resource(row) -> dict:
    (
        search_id,
        summary,
        product_identity,
        target_price,
        location,
        queries,
        exclusions,
        version,
        status,
        listing_ids,
        created_at,
        updated_at,
    ) = row
    return {
        "id": search_id,
        "summary": summary,
        "product_identity": product_identity,
        "target_price": target_price,
        "location": location,
        "queries": json.loads(queries),
        "exclusions": json.loads(exclusions),
        "version": version,
        "status": status,
        "match_count": _match_count(listing_ids),
        "created_at": _iso(created_at),
        "updated_at": _iso(updated_at),
    }


# --- Draft validation --------------------------------------------------------


def validate_api_draft(draft: dict) -> dict:
    """The draft contract: chat's per-field validation plus the cross-field
    check the JSON API adds — a query that repeats an exclusion is a
    contradiction, so it is rejected rather than silently applied."""
    clean = chat_mod.validate_draft(draft)
    excluded = {x.strip().casefold() for x in clean["exclusions"]}
    for query in clean["queries"]:
        if query.strip().casefold() in excluded:
            raise chat_mod.DraftError(
                f"query {query!r} duplicates an exclusion"
            )
    return clean


def _read_draft(handler) -> dict:
    """Parse the JSON draft body; malformed payloads are 400, not 422."""
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    try:
        body = json.loads(raw)
    except ValueError:
        raise ApiError(400, "malformed_request", "request body is not valid JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "malformed_request", "request body must be a JSON object")
    return body


# --- Fan-out ---------------------------------------------------------------


def _kick_fanout(handler, search_id: int, location: str) -> None:
    threading.Thread(
        target=fan_out,
        args=(handler.fanout_marketplaces, search_id, location),
        daemon=True,
    ).start()


# --- Endpoints -------------------------------------------------------------


def _load(conn, search_id: str) -> dict:
    try:
        key = int(search_id)
    except (TypeError, ValueError):
        raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
    row = conn.execute(
        f"SELECT {SEARCH_COLUMNS} FROM bargain_searches WHERE id=?", (key,)
    ).fetchone()
    if row is None:
        raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
    return _resource(row)


def get_one_search(handler, search_id: str) -> None:
    """Read one search resource (ticket #45)."""
    conn = get_connection()
    try:
        resource = _load(conn, search_id)
    finally:
        conn.close()
    _send_json(handler, 200, resource)


def _read_paging(qs: dict) -> tuple[int, int]:
    """page/per_page from the query string, clamped to the contract's bounds."""
    try:
        page = max(1, int((qs.get("page") or ["1"])[0]))
    except ValueError:
        raise ApiError(400, "invalid_page", "page must be a positive integer")
    try:
        per_page = int((qs.get("per_page") or [str(DEFAULT_PER_PAGE)])[0])
    except ValueError:
        raise ApiError(400, "invalid_per_page", "per_page must be a positive integer")
    return page, max(1, min(per_page, MAX_PER_PAGE))


def list_searches(qs: dict) -> dict:
    """Paginated list; items carry only id, summary, status, match_count,
    updated_at."""
    page, per_page = _read_paging(qs)
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM bargain_searches").fetchone()[0]
        rows = conn.execute(
            "SELECT id, summary, status, listing_ids, updated_at "
            "FROM bargain_searches ORDER BY id LIMIT ? OFFSET ?",
            (per_page, (page - 1) * per_page),
        ).fetchall()
    finally:
        conn.close()
    items = [
        {
            "id": sid,
            "summary": summary,
            "status": status,
            "match_count": _match_count(listing_ids),
            "updated_at": _iso(updated_at),
        }
        for sid, summary, status, listing_ids, updated_at in rows
    ]
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, math.ceil(total / per_page)),
    }


# --- Marketplace search + Listing patch (ticket #40) ----------------------


def _card(l) -> dict:
    """A raw listing card: what a Marketplace search tile carries."""
    return {
        "id": l.id,
        "title": l.title,
        "url": l.url,
        "asking_price": l.price,
        "marketplace": l.marketplace,
        "image_url": l.image_url,
    }


def marketplace_search(handler, qs: dict) -> dict:
    """Ad-hoc Marketplace search: one page of raw listing cards.

    `marketplace` defaults to the server default; `all` fans across.
    A marketplace that errors is reported in failed_marketplaces and the
    rest still render — the contract makes partial failure non-fatal."""
    page, per_page = _read_paging(qs)
    query = (qs.get("q") or [""])[0].strip()
    if not query:
        query = "HP Z440"  # same fallback as the legacy /search page
    market = (qs.get("marketplace") or [handler.default_market])[0].strip().lower()
    valid = set(handler.marketplaces) | {"all"}
    if market not in valid:
        market = handler.default_market
    location = (qs.get("location") or [""])[0].strip()

    results: dict[str, object] = {}
    failed: list[str] = []

    def run(name: str, mp) -> None:
        try:
            results[name] = mp.search(query, page, location)
        except Exception:
            failed.append(name)

    targets = handler.marketplaces if market == "all" else {market: handler.marketplaces[market]}
    threads = [threading.Thread(target=run, args=(n, m)) for n, m in targets.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    items: list[dict] = []
    total = 0
    total_pages = 1
    for name, r in results.items():
        for l in r.listings:
            l.marketplace = name
            items.append(_card(l))
        total += r.total_results
        total_pages = max(total_pages, r.total_pages)
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "failed_marketplaces": failed,
    }


def patch_listing(handler, listing_id: str) -> None:
    """Update a Listing's authored description. Setting one re-queues
    Enrichment for the listing (the authored description overrides
    Enrichment per glossary, so a fresh pass follows)."""
    body = _read_draft(handler)
    if "authored_description" not in body:
        raise ApiError(400, "malformed_request", "authored_description is required")
    text = body["authored_description"]
    if not isinstance(text, str):
        raise ApiError(400, "malformed_request", "authored_description must be a string")
    clean = text.strip() or None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT availability FROM listings WHERE id=?", (listing_id,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "listing_not_found", f"No listing with id {listing_id}")
        enhanced.set_authored_description(conn, listing_id, clean)
    finally:
        conn.close()
    _send_json(
        handler,
        200,
        {"id": listing_id, "authored_description": clean, "availability": row[0]},
    )


def create_search(handler) -> None:
    body = _read_draft(handler)
    try:
        draft = validate_api_draft(body)
    except chat_mod.DraftError as exc:
        raise ApiError(422, "invalid_draft", str(exc))
    conn = get_connection()
    try:
        search_id = chat_mod.create_search(conn, draft)
    finally:
        conn.close()
    _send_json(handler, 201, _get_resource(search_id))
    _kick_fanout(handler, search_id, draft["location"])


def update_search(handler, search_id: str) -> None:
    patch = _read_draft(handler)
    conn = get_connection()
    try:
        current = _load(conn, search_id)
        merged = {
            field: patch[field] if field in patch else current[field]
            for field in DRAFT_FIELDS
        }
        try:
            draft = validate_api_draft(merged)
        except chat_mod.DraftError as exc:
            raise ApiError(422, "invalid_draft", str(exc))
        chat_mod.update_search(conn, current["id"], draft)
    finally:
        conn.close()
    _send_json(handler, 200, _get_resource(current["id"]))
    _kick_fanout(handler, current["id"], draft["location"])


def delete_search(handler, search_id: str) -> None:
    conn = get_connection()
    try:
        _load(conn, search_id)  # 404 if missing
        chat_mod.delete_search(conn, int(search_id))
    finally:
        conn.close()
    handler._send(204, "", content_type="application/json")


def _get_resource(search_id: int) -> dict:
    conn = get_connection()
    try:
        return _load(conn, str(search_id))
    finally:
        conn.close()


def _send_json(handler, status: int, payload: dict) -> None:
    handler._send(status, json.dumps(payload), content_type="application/json")

# --- Results + per-search actions (ticket #39) ------------------------------

VALID_VERDICTS = ("match", "unsure", "not_match")
DEFAULT_VERDICT = "match,unsure"
VALID_AVAILABILITY = ("live", "dead")
VALID_SORTS = ("price_asc", "price_desc", "newest")


def _read_results_filters(qs: dict) -> tuple[set, float | None, str, str]:
    """verdict/max_price/availability/sort from the query string; defaults
    per docs/api-contract.md, garbage rejected as 400."""
    raw_verdict = (qs.get("verdict") or [DEFAULT_VERDICT])[0]
    tokens = [v.strip() for v in raw_verdict.split(",") if v.strip()]
    if "all" in tokens:
        wanted = set(VALID_VERDICTS)
    else:
        for token in tokens:
            if token not in VALID_VERDICTS:
                raise ApiError(400, "invalid_verdict", f"unknown verdict {token!r}")
        wanted = set(tokens) if tokens else set(DEFAULT_VERDICT.split(","))

    max_price: float | None = None
    raw_max = (qs.get("max_price") or [""])[0]
    if raw_max:
        try:
            max_price = float(raw_max)
        except ValueError:
            raise ApiError(400, "invalid_max_price", "max_price must be a number")

    availability = (qs.get("availability") or [""])[0]
    if availability and availability not in VALID_AVAILABILITY:
        raise ApiError(
            400, "invalid_availability", f"unknown availability {availability!r}"
        )

    sort = (qs.get("sort") or ["newest"])[0]
    if sort not in VALID_SORTS:
        raise ApiError(400, "invalid_sort", f"unknown sort {sort!r}")
    return wanted, max_price, availability, sort


def search_results(search_id: str, qs: dict) -> dict:
    """Paginated result cards for one Bargain Search. Filters and sort are
    applied before the page is sliced, per contract. The effective price
    the max_price filter compares against is the asking price — the same
    MVP shortcut the legacy enhanced view uses (flip-value math is not
    built). Rejected listings never appear, same as the legacy view."""
    page, per_page = _read_paging(qs)
    wanted, max_price, availability, sort = _read_results_filters(qs)
    try:
        key = int(search_id)
    except (TypeError, ValueError):
        raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT listing_ids FROM bargain_searches WHERE id=?", (key,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
        verdicts: dict = json.loads(row[0])
        cards: list[dict] = []
        if verdicts:
            placeholders = ",".join("?" * len(verdicts))
            rows = conn.execute(
                f"SELECT l.id, l.raw, l.authored_description, l.availability, "
                f"e.status, e.product, e.condition, e.bundle, e.confidence "
                f"FROM listings l LEFT JOIN enrichments e ON e.listing_id = l.id "
                f"WHERE l.id IN ({placeholders}) AND l.id NOT IN "
                f"(SELECT listing_id FROM rejects WHERE bargain_search_id=?) "
                f"ORDER BY l.first_seen_at DESC",
                (*verdicts.keys(), key),
            ).fetchall()
            for lid, raw, authored, avail, e_status, e_prod, e_cond, e_bun, e_conf in rows:
                data = json.loads(raw)
                verdict = verdicts.get(lid, "match")
                if verdict not in wanted:
                    continue
                price = data.get("price")
                if max_price is not None and (price is None or price > max_price):
                    continue
                card_avail = avail or "live"
                if availability and card_avail != availability:
                    continue
                enrichment = None
                if e_status is not None:
                    enrichment = {
                        "status": e_status,
                        "product": json.loads(e_prod) if e_prod else None,
                        "condition": e_cond,
                        "bundle": json.loads(e_bun) if e_bun else None,
                        "confidence": json.loads(e_conf) if e_conf else None,
                    }
                cards.append(
                    {
                        "listing_id": lid,
                        "title": data.get("title") or "",
                        "url": data.get("url") or "",
                        "asking_price": price,
                        "marketplace": data.get("marketplace") or "",
                        "image_url": data.get("image_url") or "",
                        "verdict": verdict,
                        "availability": card_avail,
                        "authored_description": authored,
                        "enrichment": enrichment,
                    }
                )
    finally:
        conn.close()
    if sort == "price_asc":
        cards.sort(key=lambda c: (c["asking_price"] is None, c["asking_price"]))
    elif sort == "price_desc":
        cards.sort(key=lambda c: (c["asking_price"] is None, -(c["asking_price"] or 0)))
    total = len(cards)
    items = cards[(page - 1) * per_page : page * per_page]
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, math.ceil(total / per_page)),
    }


def create_rejection(handler, search_id: str) -> None:
    """Reject one card: persist the rejection and feed the exclusion list.
    Same core as the legacy /reject endpoint."""
    body = _read_draft(handler)
    listing_id = body.get("listing_id")
    reason = body.get("reason")
    if not listing_id or not reason:
        raise ApiError(400, "invalid_rejection", "listing_id and reason are required")
    try:
        key = int(search_id)
    except (TypeError, ValueError):
        raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM bargain_searches WHERE id=?", (key,)
        ).fetchone() is None:
            raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
        enhanced.reject_listing(conn, key, listing_id, reason)
    finally:
        conn.close()
    _send_json(handler, 201, {"listing_id": listing_id, "reason": reason})


def create_reenrichment(handler, search_id: str) -> None:
    """Re-queue the search's missing or failed enrichments; already-enriched
    rows are never touched."""
    try:
        key = int(search_id)
    except (TypeError, ValueError):
        raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM bargain_searches WHERE id=?", (key,)
        ).fetchone() is None:
            raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
        requeued = reenrich_search(conn, key)
    finally:
        conn.close()
    _send_json(handler, 201, {"requeued": requeued})


def get_liveness(handler, search_id: str) -> None:
    """Liveness snapshot for one search: {done, banner, dead}.

    The first GET of a search that has listings kicks the background sweep
    (the legacy /search page load used to do this); later GETs and searches
    with nothing on the board never re-kick.
    """
    try:
        key = int(search_id)
    except (TypeError, ValueError):
        raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT listing_ids FROM bargain_searches WHERE id=?", (key,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "search_not_found", f"No bargain search with id {search_id}")
        has_listings = bool(json.loads(row[0] or "{}"))
    finally:
        conn.close()
    if has_listings and not liveness.kicked(key):
        liveness.start(key)
    _send_json(handler, 200, liveness.status(key))


# --- Chat Sessions + the streaming turn (ticket #42) ----------------------


def list_chat_sessions(qs: dict) -> dict:
    """Paginated list of Chat Sessions, newest first."""
    page, per_page = _read_paging(qs)
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            (per_page, (page - 1) * per_page),
        ).fetchall()
    finally:
        conn.close()
    items = [
        {
            "id": sid,
            "title": title,
            "created_at": _iso(created_at),
            "updated_at": _iso(updated_at),
        }
        for sid, title, created_at, updated_at in rows
    ]
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, math.ceil(total / per_page)),
    }


def create_chat_session(handler) -> None:
    body = _read_body(handler)
    title = body.get("title") or ""
    if not isinstance(title, str):
        raise ApiError(400, "malformed_request", "title must be a string")
    conn = get_connection()
    try:
        session_id = chat_mod.create_session(conn, title)
        created = _load_chat_session(conn, session_id)
    finally:
        conn.close()
    _send_json(handler, 201, created)


def _load_chat_session(conn, session_id: str) -> dict:
    try:
        key = int(session_id)
    except (TypeError, ValueError):
        raise ApiError(
            404, "chat_session_not_found", f"No chat session with id {session_id}"
        )
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM chat_sessions WHERE id=?",
        (key,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "chat_session_not_found", f"No chat session with id {session_id}")
    return {
        "id": row[0],
        "title": row[1],
        "created_at": _iso(row[2]),
        "updated_at": _iso(row[3]),
    }


def get_chat_session(session_id: str) -> dict:
    conn = get_connection()
    try:
        session = _load_chat_session(conn, session_id)
        rows = conn.execute(
            "SELECT role, content, created_at FROM session_messages "
            "WHERE chat_session_id=? ORDER BY rowid",
            (session["id"],),
        ).fetchall()
    finally:
        conn.close()
    return {
        "id": session["id"],
        "title": session["title"],
        "messages": [
            {"role": role, "content": content, "created_at": _iso(created_at)}
            for role, content, created_at in rows
        ],
    }


def delete_chat_session(session_id: str) -> None:
    conn = get_connection()
    try:
        try:
            key = int(session_id)
        except (TypeError, ValueError):
            raise ApiError(
                404, "chat_session_not_found", f"No chat session with id {session_id}"
            )
        # Children first: session_messages has a FK to chat_sessions and
        # enforcement is on, so deleting the parent first raises.
        cur = conn.execute("SELECT 1 FROM chat_sessions WHERE id=?", (key,))
        if cur.fetchone() is None:
            raise ApiError(
                404, "chat_session_not_found", f"No chat session with id {session_id}"
            )
        conn.execute("DELETE FROM session_messages WHERE chat_session_id=?", (key,))
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (key,))
        conn.commit()
    finally:
        conn.close()


# --- The streaming turn -----------------------------------------------------


def _sse(handler, name: str, payload: dict) -> None:
    handler.wfile.write(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
    )
    handler.wfile.flush()


def _accumulate_tool_calls(by_index: dict, deltas) -> None:
    """Merge streamed tool-call fragments by index (OpenAI incremental style:
    id/name arrive once, arguments arrive as string fragments)."""
    for d in deltas:
        idx = d.get("index", 0)
        slot = by_index.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]


def stream_turn(handler, session_id: str) -> None:
    """One chat turn as a BoldTrader SSE stream (ticket #42).

    The router's OpenAI-format chunks (reasoning_content deltas,
    content deltas, tool-call fragments) are translated into the
    contract's typed events; the router format never reaches the
    client. The user message is persisted before the first frame so a
    mid-turn disconnect loses nothing; a router failure mid-turn emits
    an `error` event and the stream closes cleanly.
    """
    body = _read_body(handler)
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ApiError(400, "malformed_request", "message is required")
    conn = get_connection()
    try:
        session = _load_chat_session(conn, session_id)
        # Persist the user message before streaming: a mid-turn disconnect
        # loses nothing (contract, ticket #42).
        chat_mod.append_session_message(conn, session["id"], "user", message)
        chat_mod._touch(conn, session["id"])
        transcript = chat_mod.load_session_transcript(conn, session["id"])
    finally:
        conn.close()

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    messages = [{"role": "system", "content": chat_mod.SYSTEM_PROMPT}]
    messages += chat_mod.reconstruct_messages(transcript)
    conn = get_connection()  # fresh conn for the turn's persistence
    try:
        for _round in range(chat_mod.MAX_TOOL_ROUNDS):
            content = ""
            by_index: dict[int, dict] = {}
            finish = None
            for chunk in router.stream_chat(
                messages, tools=chat_mod.TOOL_SCHEMAS
            ):
                choices = chunk.get("choices") or [{}]
                delta = choices[0].get("delta") or {}
                if delta.get("reasoning_content"):
                    _sse(handler, "reasoning", {"text": delta["reasoning_content"]})
                if delta.get("content"):
                    content += delta["content"]
                    _sse(handler, "token", {"text": delta["content"]})
                if delta.get("tool_calls"):
                    _accumulate_tool_calls(by_index, delta["tool_calls"])
                if choices[0].get("finish_reason"):
                    finish = choices[0]["finish_reason"]
            if finish != "tool_calls":
                reply, drafts = chat_mod.parse_reply(content)
                chat_mod.append_session_message(conn, session["id"], "assistant", reply)
                chat_mod._touch(conn, session["id"])
                for draft in drafts:
                    _sse(handler, "draft", draft)
                _sse(
                    handler,
                    "turn_complete",
                    {"session_id": session["id"], "message": reply},
                )
                return
            tool_calls = [
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["arguments"]},
                }
                for _, slot in sorted(by_index.items())
            ]
            blob = json.dumps({"content": content, "tool_calls": tool_calls})
            messages.append(
                {"role": "assistant", "content": content, "tool_calls": tool_calls}
            )
            chat_mod.append_session_message(
                conn, session["id"], "assistant", blob
            )
            chat_mod._touch(conn, session["id"])
            for call in tool_calls:
                _sse(
                    handler,
                    "tool_call",
                    {
                        "name": call["function"]["name"],
                        "arguments": json.loads(call["function"]["arguments"] or "{}"),
                    },
                )
                name, query, output = chat_mod._run_tool(call, conn, message)
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": output}
                )
                chat_mod.append_session_message(conn, session["id"], "tool", output)
                chat_mod._touch(conn, session["id"])
                _sse(
                    handler,
                    "tool_result",
                    {
                        "name": name,
                        "output": output,
                        "chip": chat_mod.chip_text(name, query, output),
                    },
                )
        # Round cap reached: one final call without tools — model must answer.
        content = ""
        for chunk in router.stream_chat(messages):
            choices = chunk.get("choices") or [{}]
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                _sse(handler, "reasoning", {"text": delta["reasoning_content"]})
            if delta.get("content"):
                content += delta["content"]
                _sse(handler, "token", {"text": delta["content"]})
        reply, drafts = chat_mod.parse_reply(content)
        chat_mod.append_session_message(conn, session["id"], "assistant", reply)
        chat_mod._touch(conn, session["id"])
        for draft in drafts:
            _sse(handler, "draft", draft)
        _sse(
            handler,
            "turn_complete",
            {"session_id": session["id"], "message": reply},
        )
    except (BrokenPipeError, ConnectionResetError):
        pass  # client hung up; the DB holds the durable state
    except Exception:
        # The raw exception (urllib3 dumps) goes to the log, not the chat:
        # the user sees one human sentence + the Regenerate affordance.
        logging.getLogger(__name__).exception("chat turn failed")
        try:
            _sse(
                handler,
                "error",
                {
                    "code": "router_error",
                    "message": "The model router (model.boldhalo.home) failed to respond. Check the router, then press Regenerate.",
                },
            )
        except (BrokenPipeError, ConnectionResetError):
            pass
    finally:
        conn.close()


def _read_body(handler) -> dict:
    """Parse the JSON request body; malformed payloads are 400."""
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    try:
        body = json.loads(raw or "{}")
    except ValueError:
        raise ApiError(400, "malformed_request", "request body is not valid JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "malformed_request", "request body must be a JSON object")
    return body


# --- Routing ---------------------------------------------------------------


def _route_chat(handler, parts: list, parsed) -> None:
    """Dispatch /api/v1/chat/... (ticket #42)."""
    if parts[3:4] != ["sessions"]:
        raise ApiError(404, "not_found", f"No route for {parsed.path}")
    if len(parts) == 4:
        if handler.command == "GET":
            _send_json(handler, 200, list_chat_sessions(parse_qs(parsed.query)))
            return
        if handler.command == "POST":
            create_chat_session(handler)
            return
    elif len(parts) == 5:
        if handler.command == "GET":
            _send_json(handler, 200, get_chat_session(parts[4]))
            return
        if handler.command == "DELETE":
            delete_chat_session(parts[4])
            handler._send(204, "", content_type="application/json")
            return
    elif len(parts) == 6 and parts[5] == "messages":
        if handler.command == "POST":
            stream_turn(handler, parts[4])
            return
    raise ApiError(404, "not_found", f"No route for {parsed.path}")


def handle(handler) -> None:
    """Dispatch a `/api/v1/` request. Called by server.Handler for that prefix."""
    parsed = urlparse(handler.path)
    parts = [p for p in parsed.path.split("/") if p]
    try:
        if parts[:2] != ["api", "v1"]:
            raise ApiError(404, "not_found", f"No route for {parsed.path}")
        if parts[2:3] == ["events"]:
            if handler.command == "GET":
                events.serve(handler)
                return
            raise ApiError(404, "not_found", f"No route for {parsed.path}")
        if parts[2:3] == ["chat"]:
            _route_chat(handler, parts, parsed)
            return
        if parts[2:3] == ["marketplace"]:
            if len(parts) == 4 and parts[3] == "search" and handler.command == "GET":
                _send_json(
                    handler, 200, marketplace_search(handler, parse_qs(parsed.query))
                )
                return
            raise ApiError(404, "not_found", f"No route for {parsed.path}")
        if parts[2:3] == ["listings"]:
            if len(parts) == 4 and handler.command == "PATCH":
                patch_listing(handler, parts[3])
                return
            raise ApiError(404, "not_found", f"No route for {parsed.path}")
        if parts[2:3] != ["searches"]:
            raise ApiError(404, "not_found", f"No route for {parsed.path}")
        if len(parts) == 3:
            if handler.command == "GET":
                _send_json(handler, 200, list_searches(parse_qs(parsed.query)))
                return
            if handler.command == "POST":
                create_search(handler)
                return
        elif len(parts) == 4:
            search_id = parts[3]
            if handler.command == "GET":
                get_one_search(handler, search_id)
                return
            if handler.command == "PATCH":
                update_search(handler, search_id)
                return
            if handler.command == "DELETE":
                delete_search(handler, search_id)
                return
        elif len(parts) == 5:
            search_id, action = parts[3], parts[4]
            if action == "results" and handler.command == "GET":
                _send_json(
                    handler, 200, search_results(search_id, parse_qs(parsed.query))
                )
                return
            if action == "rejections" and handler.command == "POST":
                create_rejection(handler, search_id)
                return
            if action == "reenrichment" and handler.command == "POST":
                create_reenrichment(handler, search_id)
                return
            if action == "liveness" and handler.command == "GET":
                get_liveness(handler, search_id)
                return
        raise ApiError(404, "not_found", f"No route for {parsed.path}")
    except ApiError as exc:
        _send_json(
            handler,
            exc.status,
            {"error": {"code": exc.code, "message": exc.message}},
        )
