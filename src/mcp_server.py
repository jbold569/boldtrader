"""MCP stdio facade over the BoldTrader HTTP JSON API (ticket #58).

ADR 0010: the HTTP API is the canonical agent surface. This module is a thin
facade on top of it — one MCP tool per agent-relevant endpoint, argument
mapping and result shaping only, zero domain logic. Every call goes out over
HTTP rather than importing the Python internals, so any drift between what an
agent does and what the SPA consumes surfaces immediately.

Run:  .venv/bin/python -m src.mcp_server
      Base URL: $BOLDTRADER_API (default http://127.0.0.1:10000)

Why hand-rolled instead of the `mcp` Python SDK: the stdio surface here is
four JSON-RPC methods (initialize, notifications/*, tools/list, tools/call)
carried as newline-delimited JSON — one screen of framing. The SDK buys a
pydantic/httpx dependency tree for a problem that is already smaller than its
install. Smaller, and with nothing to keep current: hand-rolled.
"""

from __future__ import annotations

import json
import os
import sys
import requests
from urllib.parse import urlencode

API_PREFIX = "/api/v1"
DEFAULT_BASE = "http://127.0.0.1:10000"
PROTOCOL_VERSION = "2024-11-05"
REQUEST_TIMEOUT = 120

_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_STRS = {"type": "array", "items": {"type": "string"}}


# The tool table: one entry per agent-relevant endpoint. `path_args` fill the
# `{placeholders}` in the path template, `body_args` become the JSON request
# body exactly as supplied (explicit nulls included — that is how a PATCH
# clears a field), and every other supplied argument becomes a query param
# (nulls dropped: an absent filter beats a null one server-side).
_TOOLS = [
    {
        "name": "create_search",
        "description": (
            "Create and launch a Bargain Search from a draft. Kicks fan-out + "
            "enrichment in the background and returns the search resource with "
            "its `id`; poll that search with get_search until status is "
            "'complete', then read the hits with search_results. Required: "
            "summary, product_identity (a prose description of the thing you "
            "want), queries."
        ),
        "method": "POST",
        "path": "/searches",
        "path_args": [],
        "body_args": [
            "summary",
            "product_identity",
            "queries",
            "exclusions",
            "target_price",
            "location",
        ],
        "required": ["summary", "product_identity", "queries"],
        "props": {
            "summary": _STR,
            "product_identity": _STR,
            "queries": _STRS,
            "exclusions": _STRS,
            "target_price": _NUM,
            "location": _STR,
        },
    },
    {
        "name": "list_searches",
        "description": (
            "List Bargain Searches (id, summary, status, match_count, "
            "updated_at), newest by id. Use it to find a search_id for "
            "get_search / search_results."
        ),
        "method": "GET",
        "path": "/searches",
        "path_args": [],
        "body_args": [],
        "props": {"page": _INT, "per_page": _INT},
    },
    {
        "name": "get_search",
        "description": (
            "Read one Bargain Search: version, status "
            "(active|running|enriching|complete), match_count, timestamps."
        ),
        "method": "GET",
        "path": "/searches/{search_id}",
        "path_args": ["search_id"],
        "body_args": [],
        "props": {"search_id": _INT},
    },
    {
        "name": "update_search",
        "description": (
            "Partial update of a Bargain Search draft; bumps `version` and "
            "re-kicks fan-out. Send only the fields you are changing. Same "
            "field rules as create_search."
        ),
        "method": "PATCH",
        "path": "/searches/{search_id}",
        "path_args": ["search_id"],
        "body_args": [
            "summary",
            "product_identity",
            "queries",
            "exclusions",
            "target_price",
            "location",
        ],
        "required": [],
        "props": {
            "search_id": _INT,
            "summary": _STR,
            "product_identity": _STR,
            "queries": _STRS,
            "exclusions": _STRS,
            "target_price": _NUM,
            "location": _STR,
        },
    },
    {
        "name": "delete_search",
        "description": "Delete a Bargain Search. Irreversible.",
        "method": "DELETE",
        "path": "/searches/{search_id}",
        "path_args": ["search_id"],
        "body_args": [],
        "props": {"search_id": _INT},
    },
    {
        "name": "run_search",
        "description": (
            "Re-run an existing search's fan-out without touching its draft "
            "(no version bump). Use after fixing the identity description or "
            "restoring rejections."
        ),
        "method": "POST",
        "path": "/searches/{search_id}/run",
        "path_args": ["search_id"],
        "body_args": [],
        "props": {"search_id": _INT},
    },
    {
        "name": "search_results",
        "description": (
            "Paginated result cards for one Bargain Search, with each card's "
            "computed effective_price, fair_price and margin_pct. Filters "
            "apply server-side before paging: verdict is a comma list of "
            "match|unsure|not_match or 'all' (default match,unsure); "
            "max_price compares effective price, not the ask; availability "
            "live|dead; sort price_asc|price_desc|newest."
        ),
        "method": "GET",
        "path": "/searches/{search_id}/results",
        "path_args": ["search_id"],
        "body_args": [],
        "props": {
            "search_id": _INT,
            "verdict": _STR,
            "max_price": _NUM,
            "availability": _STR,
            "sort": _STR,
            "page": _INT,
            "per_page": _INT,
        },
    },
    {
        "name": "marketplace_search",
        "description": (
            "Ad-hoc marketplace query, no search context. Returns raw listing "
            "cards (id, title, url, asking_price, marketplace, image_url) "
            "plus any `failed_marketplaces`. marketplace defaults to the "
            "server default; 'all' fans across every marketplace."
        ),
        "method": "GET",
        "path": "/marketplace/search",
        "path_args": [],
        "body_args": [],
        "required": ["q"],
        "props": {
            "q": _STR,
            "marketplace": _STR,
            "location": _STR,
            "page": _INT,
        },
    },
    {
        "name": "patch_listing",
        "description": (
            "Set a listing's authored_description — what you assert the item "
            "actually is. This overrides AI Enrichment for that listing and "
            "re-queues enrichment. Returns {id, authored_description, "
            "availability}."
        ),
        "method": "PATCH",
        "path": "/listings/{id}",
        "path_args": ["id"],
        "body_args": ["authored_description"],
        "required": ["authored_description"],
        "props": {"id": _INT, "authored_description": _STR},
    },
    {
        "name": "create_rejection",
        "description": (
            "Reject one card in a search: the reason is fed into the next "
            "sift's exclusion list, so it should say *why* this listing is "
            "not the product ('not a Z440, it's a Z230'), not just 'no'."
        ),
        "method": "POST",
        "path": "/searches/{search_id}/rejections",
        "path_args": ["search_id"],
        "body_args": ["listing_id", "reason"],
        "required": ["listing_id", "reason"],
        "props": {"search_id": _INT, "listing_id": _STR, "reason": _STR},
    },
    {
        "name": "restore_rejection",
        "description": (
            "Undo a rejection: the listing is asserted to BE the product, its "
            "exclusion drops, its verdict becomes a match. Returns the "
            "updated search resource. Follow with run_search to re-sift."
        ),
        "method": "DELETE",
        "path": "/searches/{search_id}/rejections/{listing_id}",
        "path_args": ["search_id", "listing_id"],
        "body_args": [],
        "props": {"search_id": _INT, "listing_id": _STR},
    },
    {
        "name": "list_identities",
        "description": (
            "List Product Identities (id, description, deal_threshold, "
            "synthesized_at). A null deal_threshold means the identity falls "
            "back to the global threshold from get_settings."
        ),
        "method": "GET",
        "path": "/product-identities",
        "path_args": [],
        "body_args": [],
        "props": {"page": _INT, "per_page": _INT},
    },
    {
        "name": "get_identity",
        "description": "Read one Product Identity resource by id.",
        "method": "GET",
        "path": "/product-identities/{identity_id}",
        "path_args": ["identity_id"],
        "body_args": [],
        "props": {"identity_id": _INT},
    },
    {
        "name": "patch_identity",
        "description": (
            "Hand-edit a Product Identity: `description` (non-empty prose) "
            "and/or `deal_threshold` (positive percentage, or null to clear "
            "the override). A hand-edit is not a synthesis, so "
            "synthesized_at is untouched. Editing the description makes "
            "existing verdicts over it stale (verdict_stale=true)."
        ),
        "method": "PATCH",
        "path": "/product-identities/{identity_id}",
        "path_args": ["identity_id"],
        "body_args": ["description", "deal_threshold"],
        "required": [],
        "props": {"identity_id": _INT, "description": _STR, "deal_threshold": _NUM},
    },
    {
        "name": "merge_identities",
        "description": (
            "Merge a duplicate Product Identity into the winner: every "
            "listing, price observation and search mapping pointing at the "
            "loser is re-pointed at the winner, then the loser is deleted. "
            "One transaction. Returns the winner resource. Self-merge and "
            "unknown ids are rejected."
        ),
        "method": "POST",
        "path": "/product-identities/{identity_id}/merge",
        "path_args": ["identity_id"],
        "body_args": ["into"],
        "required": ["into"],
        "props": {"identity_id": _INT, "into": _INT},
    },
    {
        "name": "retune_identity",
        "description": (
            "Ask the model to rewrite a Product Identity description from the "
            "accumulated evidence (matched listings, rejections, authored "
            "descriptions) of every search mapped to it. Sets "
            "synthesized_at on success; a no-op if the model returns blank "
            "or identical text. Failure leaves nothing persisted."
        ),
        "method": "POST",
        "path": "/product-identities/{identity_id}/retune",
        "path_args": ["identity_id"],
        "body_args": [],
        "props": {"identity_id": _INT},
    },
    {
        "name": "list_deals",
        "description": (
            "The flat deal feed: every identified listing whose effective "
            "price clears its identity's deal threshold, sorted by margin. "
            "Filters: sort margin_desc|margin_asc, max_price (effective "
            "price), availability live|dead, product_identity_id, "
            "marketplace (exact). Listings with no fair price yet (cold "
            "start) never appear."
        ),
        "method": "GET",
        "path": "/deals",
        "path_args": [],
        "body_args": [],
        "props": {
            "page": _INT,
            "per_page": _INT,
            "sort": _STR,
            "max_price": _NUM,
            "availability": _STR,
            "product_identity_id": _INT,
            "marketplace": _STR,
        },
    },
    {
        "name": "get_settings",
        "description": (
            "Read the app settings; currently {deal_threshold}, the global "
            "deal margin percentage used when a Product Identity sets no "
            "override."
        ),
        "method": "GET",
        "path": "/settings",
        "path_args": [],
        "body_args": [],
        "props": {},
    },
    {
        "name": "update_settings",
        "description": (
            "Change the global deal_threshold percentage (positive number). "
            "Returns the full settings object."
        ),
        "method": "PATCH",
        "path": "/settings",
        "path_args": [],
        "body_args": ["deal_threshold"],
        "required": [],
        "props": {"deal_threshold": _NUM},
    },
    {
        "name": "reenrich_search",
        "description": (
            "Re-queue the missing or failed Enrichment rows for one search's "
            "match/unsure listings; already-enriched rows are untouched, so "
            "it is safe to re-run. Returns {requeued: n}."
        ),
        "method": "POST",
        "path": "/searches/{search_id}/reenrichment",
        "path_args": ["search_id"],
        "body_args": [],
        "props": {"search_id": _INT},
    },
    {
        "name": "correct_enrichment",
        "description": (
            "A Correction: hand-set a listing's enriched facts. Send at least "
            "one of product_identity (a description string; matched if it "
            "exists, otherwise a new identity is minted), condition, or "
            "bundle ([{description, confidence}]). Only the fields you send "
            "change. The listing is then frozen — no later AI enrichment "
            "pass overwrites it. Returns the corrected record."
        ),
        "method": "PATCH",
        "path": "/enrichments/{listing_id}",
        "path_args": ["listing_id"],
        "body_args": ["product_identity", "condition", "bundle"],
        "required": [],
        "props": {
            "listing_id": _STR,
            "product_identity": _STR,
            "condition": _STR,
            "bundle": {"type": "array", "items": {"type": "object"}},
        },
    },
]


def tool_definitions() -> list:
    """The MCP tools/list payload: schemas are derived from the endpoint table.

    Path arguments are always required — they live in the URL — so they are
    merged into `required` here even when the table entry omits them."""
    out = []
    for t in _TOOLS:
        required = list(t.get("required") or [])
        for arg in t["path_args"]:
            if arg not in required:
                required.append(arg)
        out.append(
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": t["props"],
                    "required": required,
                },
            }
        )
    return out


def _url(base: str, tool: dict, arguments: dict) -> str:
    path = tool["path"].format(**{k: arguments[k] for k in tool["path_args"]})
    body_names = set(tool["body_args"])
    query = {
        k: v
        for k, v in arguments.items()
        if k not in tool["path_args"] and k not in body_names and v is not None
    }
    url = f"{base.rstrip('/')}{API_PREFIX}{path}"
    if query:
        url += "?" + urlencode(query)
    return url


def _request_json(resp) -> dict:
    text = resp.read().decode("utf-8") if hasattr(resp, "read") else resp.text
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


def probe(base: str) -> None:
    """Fail loudly at startup if the API is not there, with the fix."""
    try:
        requests.get(f"{base.rstrip('/')}{API_PREFIX}/settings", timeout=10)
    except requests.RequestException as exc:
        raise SystemExit(
            f"BoldTrader API unreachable at {base} ({exc}).\n"
            "Start it first:  .venv/bin/python -m src.server --port 10000\n"
            "Or point this server elsewhere with the BOLDTRADER_API "
            "environment variable."
        )


def call_tool(name: str, arguments: dict, base: str) -> dict:
    """Map one tool call onto its endpoint and shape the response into an MCP
    tool result. Non-2xx is a tool error carrying the API's own error code."""
    tool = next((t for t in _TOOLS if t["name"] == name), None)
    if tool is None:
        return _tool_result(f"unknown tool: {name}", error=True)
    missing = [k for k in tool["path_args"] if k not in arguments]
    if missing:
        return _tool_result(
            f"missing required argument(s): {', '.join(missing)} "
            f"for tool {name} (path {tool['path']})",
            error=True,
        )
    body = {k: arguments[k] for k in tool["body_args"] if k in arguments}
    try:
        resp = requests.request(
            tool["method"],
            _url(base, tool, arguments),
            json=body if tool["body_args"] else None,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return _tool_result(f"api_unreachable: {base} — {exc}", error=True)
    payload = _request_json(resp)
    if resp.status_code >= 400:
        err = payload.get("error") or {}
        return _tool_result(
            f"HTTP {resp.status_code} {err.get('code', 'error')}: "
            f"{err.get('message', 'no detail')}",
            error=True,
        )
    if resp.status_code == 204 or not payload:
        return _tool_result("deleted")
    return _tool_result(json.dumps(payload))


def _tool_result(text: str, error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": error,
    }


def handle_message(msg: dict, base: str) -> dict | None:
    """One JSON-RPC request -> one response (None for notifications)."""
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "boldtrader",
                    "title": "BoldTrader deal hunting",
                },
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": tool_definitions()},
        }
    if method == "tools/call":
        params = msg.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": call_tool(
                params.get("name"), params.get("arguments") or {}, base
            ),
        }
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve(stdin, stdout, base: str) -> None:
    """Newline-delimited JSON-RPC over the given streams, until EOF."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            reply = handle_message(msg, base)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def main() -> None:
    base = os.environ.get("BOLDTRADER_API") or DEFAULT_BASE
    probe(base)
    serve(sys.stdin, sys.stdout, base)


if __name__ == "__main__":
    main()
