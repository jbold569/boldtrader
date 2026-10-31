"""Tests for the MCP stdio facade (ticket #58).

The facade is argument mapping + result shaping over the HTTP API and nothing
else, so the tests drive a recording stub HTTP server and assert exactly what
request each tool issues, plus the handshake and the startup-probe failure.
"""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import mcp_server


class _Stub(BaseHTTPRequestHandler):
    """Records every request; replies with a canned status+JSON."""

    recorded: list = []
    response = (200, {"ok": True})

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        _Stub.recorded.append(
            {"method": self.command, "path": self.path, "body": json.loads(raw) if raw else None}
        )
        status, payload = _Stub.response
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = do_DELETE = _handle

    def log_message(self, format, *args) -> None:
        pass


@pytest.fixture
def stub():
    _Stub.recorded = []
    _Stub.response = (200, {"ok": True})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def drive(messages, base="http://127.0.0.1:1"):
    """Feed newline-delimited JSON-RPC in, return the parsed replies out."""
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    out = io.StringIO()
    mcp_server.serve(inp, out, base)
    out.seek(0)
    return [json.loads(line) for line in out if line.strip()]


def call(name, arguments, base):
    """One tools/call round-trip; returns the MCP result dict."""
    replies = drive(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ],
        base,
    )
    return replies[0]["result"]


# --- Tool table -----------------------------------------------------------

EXPECTED_TOOLS = {
    "create_search",
    "list_searches",
    "get_search",
    "update_search",
    "delete_search",
    "run_search",
    "search_results",
    "marketplace_search",
    "patch_listing",
    "create_rejection",
    "restore_rejection",
    "list_identities",
    "get_identity",
    "patch_identity",
    "merge_identities",
    "retune_identity",
    "list_deals",
    "get_settings",
    "update_settings",
    "reenrich_search",
    "correct_enrichment",
}


def test_tools_list_exposes_every_endpoint():
    tools = mcp_server.tool_definitions()
    assert {t["name"] for t in tools} == EXPECTED_TOOLS


def test_each_tool_has_valid_schema():
    for tool in mcp_server.tool_definitions():
        assert tool["description"] and len(tool["description"]) > 30
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        for prop in schema["properties"].values():
            assert "type" in prop
        for req in schema.get("required", []):
            assert req in schema["properties"]


# --- Handshake -------------------------------------------------------------


def test_initialize_handshake():
    replies = drive(
        [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
    )
    assert len(replies) == 1
    result = replies[0]["result"]
    assert result["protocolVersion"]
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "boldtrader"


def test_initialized_notification_gets_no_reply():
    out = io.StringIO()
    mcp_server.serve(
        io.StringIO(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        ),
        out,
        "http://127.0.0.1:1",
    )
    assert out.getvalue() == ""


def test_unknown_method_is_jsonrpc_error():
    replies = drive([{"jsonrpc": "2.0", "id": 7, "method": "prompts/list"}])
    assert replies[0]["error"]["code"] == -32601
    assert replies[0]["id"] == 7


def test_unparsable_line_is_parse_error():
    out = io.StringIO()
    mcp_server.serve(io.StringIO("not json\n"), out, "http://127.0.0.1:1")
    out.seek(0)
    reply = json.loads(out.read())
    assert reply["error"]["code"] == -32700


# --- Argument mapping ------------------------------------------------------


def test_create_search_maps_body(stub):
    draft = {
        "summary": "HP Z440 under $300",
        "product_identity": "HP Z440",
        "queries": ["hp z440"],
        "exclusions": ["no monitor"],
        "target_price": 300.0,
        "location": "Kenmore, WA",
    }
    call("create_search", draft, stub)
    assert _Stub.recorded[0]["method"] == "POST"
    assert _Stub.recorded[0]["path"] == "/api/v1/searches"
    assert _Stub.recorded[0]["body"] == draft


def test_search_results_maps_query(stub):
    call(
        "search_results",
        {
            "search_id": 3,
            "verdict": "match",
            "max_price": 250,
            "availability": "live",
            "sort": "price_asc",
            "page": 2,
        },
        stub,
    )
    rec = _Stub.recorded[0]
    assert rec["method"] == "GET"
    assert rec["path"].startswith("/api/v1/searches/3/results?")
    query = rec["path"].split("?", 1)[1]
    assert "verdict=match" in query
    assert "max_price=250" in query
    assert "availability=live" in query
    assert "sort=price_asc" in query
    assert "page=2" in query


def test_omitted_query_args_are_dropped(stub):
    call("list_searches", {"page": 3}, stub)
    assert _Stub.recorded[0]["path"] == "/api/v1/searches?page=3"


def test_none_query_args_are_dropped(stub):
    call("list_deals", {"max_price": None, "marketplace": "offerup"}, stub)
    assert _Stub.recorded[0]["path"] == "/api/v1/deals?marketplace=offerup"


def test_explicit_null_reaches_body(stub):
    """PATCH-to-clear: a null deal_threshold must be sent, not dropped."""
    call("update_settings", {"deal_threshold": None}, stub)
    assert _Stub.recorded[0]["body"] == {"deal_threshold": None}


def test_path_params_are_substituted(stub):
    call("restore_rejection", {"search_id": 3, "listing_id": "offup:1234"}, stub)
    rec = _Stub.recorded[0]
    assert rec["method"] == "DELETE"
    # ':' is legal unencoded in a path segment; the API's urlparse does not
    # unquote, so percent-encoding would break the id lookup.
    assert rec["path"] == "/api/v1/searches/3/rejections/offup:1234"


def test_correct_enrichment_maps_path_and_body(stub):
    call(
        "correct_enrichment",
        {
            "listing_id": "offup:9",
            "condition": "complete",
            "bundle": [{"description": "mouse", "confidence": "high"}],
        },
        stub,
    )
    rec = _Stub.recorded[0]
    assert rec["method"] == "PATCH"
    assert rec["path"] == "/api/v1/enrichments/offup:9"
    assert rec["body"]["condition"] == "complete"


def test_identity_merge_and_retune(stub):
    call("merge_identities", {"identity_id": 4, "into": 2}, stub)
    assert _Stub.recorded[0]["method"] == "POST"
    assert _Stub.recorded[0]["path"] == "/api/v1/product-identities/4/merge"
    assert _Stub.recorded[0]["body"] == {"into": 2}
    call("retune_identity", {"identity_id": 4}, stub)
    assert _Stub.recorded[1]["path"] == "/api/v1/product-identities/4/retune"


def test_marketplace_search_query(stub):
    call(
        "marketplace_search",
        {"q": "hp z440", "marketplace": "all", "location": "Renton, WA", "page": 1},
        stub,
    )
    rec = _Stub.recorded[0]
    assert rec["method"] == "GET"
    assert (
        rec["path"]
        == "/api/v1/marketplace/search?q=hp+z440&marketplace=all&location=Renton%2C+WA&page=1"
    )


def test_empty_body_tools(stub):
    call("run_search", {"search_id": 5}, stub)
    call("reenrich_search", {"search_id": 5}, stub)
    call("get_settings", {}, stub)
    assert [r["path"] for r in _Stub.recorded] == [
        "/api/v1/searches/5/run",
        "/api/v1/searches/5/reenrichment",
        "/api/v1/settings",
    ]


# --- Result shaping --------------------------------------------------------


def test_success_returns_json_text(stub):
    payload = {"items": [{"id": 1}], "page": 1, "per_page": 50, "total": 1, "total_pages": 1}
    _Stub.response = (200, payload)
    result = call("list_searches", {}, stub)
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == payload


def test_api_error_becomes_isError_result(stub):
    _Stub.response = (422, {"error": {"code": "invalid_draft", "message": "summary required"}})
    result = call("create_search", {}, stub)
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "invalid_draft" in text
    assert "summary required" in text


def test_empty_response_body_shapes_ok(stub):
    class _Empty(BaseHTTPRequestHandler):
        def do_DELETE(self):
            _Stub.recorded.append({"method": "DELETE", "path": self.path, "body": None})
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Empty)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        result = call("delete_search", {"search_id": 2}, base)
        assert result["isError"] is False
        assert result["content"][0]["text"] == "deleted"
    finally:
        httpd.shutdown()


def test_unknown_tool_is_error_result(stub):
    result = call("does_not_exist", {}, stub)
    assert result["isError"] is True
    assert "unknown tool" in result["content"][0]["text"].lower()


# --- Startup probe ---------------------------------------------------------


def test_probe_passes_when_api_is_up(stub):
    mcp_server.probe(stub)  # must not raise


def test_probe_dies_loudly_with_instructions():
    with pytest.raises(SystemExit) as exc:
        mcp_server.probe("http://127.0.0.1:1")
    msg = str(exc.value)
    assert "python -m src.server" in msg


def test_main_probes_before_serving(monkeypatch):
    monkeypatch.setenv("BOLDTRADER_API", "http://127.0.0.1:1")
    with pytest.raises(SystemExit) as exc:
        mcp_server.main()
    assert "python -m src.server" in str(exc.value)


def test_main_serves_handshake_against_live_api(stub, monkeypatch):
    monkeypatch.setenv("BOLDTRADER_API", stub)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
    )
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    mcp_server.main()
    out.seek(0)
    reply = json.loads(out.read())
    assert reply["result"]["serverInfo"]["name"] == "boldtrader"


def test_missing_path_arg_is_error_not_crash(stub):
    # An agent passing the wrong argument name must not take down the
    # stdio server; it gets an isError result instead.
    result = call("get_search", {"bogus": 999999}, stub)
    assert result["isError"] is True
    assert "search_id" in result["content"][0]["text"]
    # the process survived: a valid call right after still works
    result2 = call("get_search", {"search_id": 1}, stub)
    assert result2["isError"] is False
