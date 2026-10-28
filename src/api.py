"""Bargain Search JSON API (ticket #38) — the `/api/v1/searches` surface.

Additive over the existing chat/search persistence: list, create, partial
update, delete per docs/api-contract.md. snake_case in and out, ISO 8601
timestamps, JSON error bodies on every non-2xx. Create and update kick
fan-out in a background thread after the response is on the wire, exactly
as the legacy /confirm and /search paths do.
"""

from __future__ import annotations

import json
import math
import threading
from urllib.parse import parse_qs, urlparse

from . import chat as chat_mod
from .db import get_connection
from .fanout import fan_out

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


def list_searches(qs: dict) -> dict:
    """Paginated list; items carry only id, summary, status, match_count,
    updated_at."""
    try:
        page = max(1, int((qs.get("page") or ["1"])[0]))
    except ValueError:
        raise ApiError(400, "invalid_page", "page must be a positive integer")
    try:
        per_page = int((qs.get("per_page") or [str(DEFAULT_PER_PAGE)])[0])
    except ValueError:
        raise ApiError(400, "invalid_per_page", "per_page must be a positive integer")
    per_page = max(1, min(per_page, MAX_PER_PAGE))
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


# --- Routing ---------------------------------------------------------------


def handle(handler) -> None:
    """Dispatch a `/api/v1/` request. Called by server.Handler for that prefix."""
    parsed = urlparse(handler.path)
    parts = [p for p in parsed.path.split("/") if p]
    try:
        if parts[:2] != ["api", "v1"]:
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
            if handler.command == "PATCH":
                update_search(handler, search_id)
                return
            if handler.command == "DELETE":
                delete_search(handler, search_id)
                return
        raise ApiError(404, "not_found", f"No route for {parsed.path}")
    except ApiError as exc:
        _send_json(
            handler,
            exc.status,
            {"error": {"code": exc.code, "message": exc.message}},
        )
