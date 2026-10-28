"""SPA static serving tests (ticket #43, migration plan M2).

Live ThreadingHTTPServer over a temp DB (style of tests/test_api_searches.py)
with frontend/dist pointed at a synthetic built bundle. Asserts the serving
contract: non-/api GETs resolve files from frontend/dist, unknown paths
fall through to index.html (SPA fallback), hashed assets get the right
Content-Type, /api/v1/* still works on the same port, and startup fails
fast when dist/ is missing.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.db import init_db

INDEX_SENTINEL = "<!doctype html><title>boldtrader spa shell</title><div id=root></div>"
ASSET_BODY = "console.log('built asset');"


def make_dist(root):
    """A synthetic Vite build output: index.html + hashed asset dir."""
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_SENTINEL, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text(ASSET_BODY, encoding="utf-8")
    return dist


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port, temp DB, dist pointed at a fake build."""
    db_path = tmp_path / "spa.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(db_path))
    init_db(db_path).close()

    from src import server as server_mod

    dist = make_dist(tmp_path)
    monkeypatch.setattr(server_mod, "FRONTEND_DIST", dist)
    server_mod.Handler.marketplaces = {}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "offerup"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url: str):
    return urllib.request.urlopen(url)


# --- (a) fail fast when dist/ is missing -------------------------------------


def test_missing_dist_raises_systemexit_with_clear_error(tmp_path):
    from src import server as server_mod

    with pytest.raises(SystemExit) as exc:
        server_mod.check_frontend_dist(tmp_path / "nope")
    text = " ".join(str(a) for a in exc.value.args)
    assert "frontend" in text and "build" in text, text


# --- (b) GET / serves an HTML page (old home stands until M8) ---------------


def test_root_serves_html(site):
    with get(site + "/") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        assert len(resp.read()) > 0


# --- (c) unknown path falls through to the SPA index ------------------------


def test_unknown_route_returns_spa_index(site):
    with get(site + "/some/unknown/route") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        assert resp.read().decode("utf-8") == INDEX_SENTINEL


def test_unknown_path_with_weird_suffix_still_gets_index(site):
    with get(site + "/chat/99/whatever-nonsense") as resp:
        assert resp.status == 200
        assert resp.read().decode("utf-8") == INDEX_SENTINEL


# --- (d) built assets are served with the right Content-Type ----------------


def test_asset_served_with_content_type(site):
    with get(site + "/assets/index-abc123.js") as resp:
        assert resp.status == 200
        assert resp.read().decode("utf-8") == ASSET_BODY
    # Content-Type per extension (read on a fresh request; body already consumed)
    req = urllib.request.Request(site + "/assets/index-abc123.js", method="GET")
    with urllib.request.urlopen(req) as resp:
        assert "javascript" in resp.headers["Content-Type"]


# --- (e) /api/v1/* keeps working through the same handler -------------------


VALID_DRAFT = {
    "summary": "HP Z440 workstations under $300",
    "product_identity": "HP Z440",
    "queries": ["hp z440"],
    "exclusions": ["parts only"],
    "target_price": 300.0,
    "location": "Kenmore, WA",
}


def test_api_searches_still_works_same_port(site):
    data = json.dumps(VALID_DRAFT).encode("utf-8")
    req = urllib.request.Request(
        site + "/api/v1/searches",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as created:
        assert created.status == 201
    with get(site + "/api/v1/searches") as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert body["total"] == 1
    assert body["items"][0]["summary"] == VALID_DRAFT["summary"]

def test_path_traversal_does_not_escape_dist(site):
    # Percent-encoded `..` segments survive the client and reach the handler:
    # the resolve() guard must refuse them, serving the SPA shell instead.
    for target in (
        "/%2e%2e/%2e%2e/etc/passwd",
        "/assets/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd",
    ):
        with urllib.request.urlopen(site + target) as resp:
            body = resp.read().decode("utf-8", "replace")
        assert "root:x:" not in body, f"escaped dist via {target}"
