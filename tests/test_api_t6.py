"""Contract tests for JSON 500s (ticket #57).

`api.handle` must never let an unexpected (non-ApiError) exception escape to
BaseHTTPRequestHandler's HTML traceback page: the client always gets
`{"error": {"code": "internal", "message": ...}}` with status 500, and the
traceback goes to the server log only. Live-server pattern from the other
API tests; nothing external is touched.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import api as api_mod
from src.db import init_db


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB; nothing external."""
    path = tmp_path / "t6.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    init_db(path).close()

    from src import server as server_mod

    server_mod.Handler.marketplaces = {}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "offerup"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(method: str, url: str, body=None):
    """One HTTP round-trip; returns (status, parsed_json_or_None, headers)."""
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else None), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return exc.code, parsed, dict(exc.headers)


def boom(*args, **kwargs):
    raise RuntimeError("kaboom")


def test_unexpected_exception_returns_json_500(site, monkeypatch):
    monkeypatch.setattr(api_mod, "list_searches", boom)
    status, body, headers = call("GET", site + "/api/v1/searches")
    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    # The body parsed as JSON (parsed is not None) — it is not an HTML page.
    assert body is not None
    assert "<html" not in json.dumps(body)
    assert body["error"]["code"] == "internal"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def test_unexpected_exception_traceback_is_logged(site, monkeypatch, caplog):
    monkeypatch.setattr(api_mod, "list_searches", boom)
    with caplog.at_level(logging.ERROR):
        status, _, _ = call("GET", site + "/api/v1/searches")
    assert status == 500
    assert "kaboom" in caplog.text
    assert "Traceback" in caplog.text
