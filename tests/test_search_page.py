"""Route-level tests for the Search page (ticket #9).

GET /search is the raw keyword search (query / location / marketplace with
pagination, the behavior /raw used to have). The Advanced toggle exposes the
Bargain Search form: valid submissions create the search, kick fan-out and
redirect to the enhanced view; invalid ones re-render the form with the
error and create nothing. /raw is gone (404). Fan-out is faked; the network
is never touched.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest

from src.db import init_db
from src.marketplace import Listing, Marketplace, SearchResult

VALID_FORM = {
    "summary": "HP Z440 workstations, complete, <= $200",
    "product_identity": "HP Z440 workstation",
    "queries": "HP Z440\nused HP Z440",
    "exclusions": "parts only",
    "target_price": "200",
    "location": "Kenmore, WA",
}


class FakeMarketplace(Marketplace):
    """One page of deterministic listings per search call."""

    name = "fake"

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        return SearchResult(
            listings=[
                Listing(
                    id=f"{query}-{page}",
                    title=f"Listing {query} page {page}",
                    price=99.0,
                    url=f"https://example.invalid/{query}/{page}",
                )
            ],
            total_results=150,
            page=page,
            page_size=50,
            total_pages=3,
        )


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB and fake marketplaces."""
    path = tmp_path / "site.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    init_db(path).close()

    from src import server as server_mod

    server_mod.Handler.marketplaces = {"offerup": FakeMarketplace()}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "offerup"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface 3xx as an HTTPError to the caller


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.read().decode("utf-8")


def post(url: str, form: dict, follow: bool = True) -> tuple[int, str, dict]:
    data = urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    if follow:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


def db_rows(sql: str):
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# --- GET /search: raw keyword search -----------------------------------------

def test_search_renders_raw_search_controls(site):
    status, body = get(site + "/search")
    assert status == 200
    assert 'action="/search"' in body
    assert 'name="q"' in body and 'name="loc"' in body and 'name="m"' in body
    assert '<option value="all"' in body


def test_search_empty_query_falls_back_to_default_like_raw(site):
    status, body = get(site + "/search?q=")
    assert status == 200
    assert "results for <strong>HP Z440</strong>" in body


def test_search_shows_results_and_pagination(site):
    status, body = get(site + "/search?q=lamp&page=2")
    assert status == 200
    assert "Listing lamp page 2" in body
    assert "page=1" in body and "page=3" in body  # pager links stay on /search
    assert "Next →" in body and "← Prev" in body


def test_search_pagination_links_point_at_search(site):
    status, body = get(site + "/search?q=lamp&page=1")
    assert 'href="/search?q=lamp' in body


# --- Advanced toggle ----------------------------------------------------------

def test_advanced_form_present_and_hidden_by_default(site):
    status, body = get(site + "/search")
    assert 'id="advanced-toggle"' in body
    assert 'id="advanced" hidden' in body
    for field in ("summary", "product_identity", "queries", "exclusions", "target_price", "location"):
        assert f'name="{field}"' in body


# --- POST /search: advanced Bargain Search create -----------------------------

def test_advanced_valid_creates_search_and_redirects(site, monkeypatch):
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "src.server.fan_out",
        lambda mkts, sid, loc: recorded.append((sid, loc)),
    )
    code, _, headers = post(site + "/search", VALID_FORM, follow=False)
    assert code == 303
    assert headers["Location"] == "/search?id=1"
    rows = db_rows("SELECT summary, product_identity, location FROM bargain_searches")
    assert rows == [
        (VALID_FORM["summary"], VALID_FORM["product_identity"], "Kenmore, WA")
    ]
    # fan-out kicked off after the response was sent
    deadline = time.time() + 2
    while time.time() < deadline and not recorded:
        time.sleep(0.01)
    assert recorded == [(1, "Kenmore, WA")]


def test_advanced_redirect_target_is_enhanced_view(site, monkeypatch):
    monkeypatch.setattr("src.server.fan_out", lambda *a: None)
    _, _, headers = post(site + "/search", VALID_FORM, follow=False)
    status, body = get(site + headers["Location"])
    assert status == 200


def test_empty_summary_filled_from_product_identity(site, monkeypatch):
    monkeypatch.setattr("src.server.fan_out", lambda *a: None)
    post(site + "/search", dict(VALID_FORM, summary=""), follow=False)
    summary = db_rows("SELECT summary FROM bargain_searches")[0][0]
    assert summary == VALID_FORM["product_identity"]


def test_invalid_submission_rerenders_form_and_creates_nothing(site, monkeypatch):
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "src.server.fan_out",
        lambda mkts, sid, loc: recorded.append((sid, loc)),
    )
    form = {k: v for k, v in VALID_FORM.items() if k != "queries"}
    code, body, headers = post(site + "/search", form, follow=False)
    assert code == 200  # no redirect
    assert "queries must be a non-empty list of strings" in body
    # submitted values come back so they can be fixed in place
    assert 'value="HP Z440 workstation"' in body
    assert 'value="200"' in body
    # advanced section is revealed so the error is actionable
    assert '<div id="advanced">' in body
    assert db_rows("SELECT COUNT(*) FROM bargain_searches")[0][0] == 0
    assert recorded == []


# --- /raw removed -------------------------------------------------------------

@pytest.mark.xfail(reason="SPA fallback (ticket #43, M2) serves the shell at /raw")
def test_raw_returns_404(site):
    # /raw was never a real page; M2's SPA fallback now answers it with the shell.
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(site + "/raw")
    assert exc.value.code == 404


def test_no_app_links_point_at_raw(site):
    for path in ("/", "/searches", "/search", "/chat"):
        _, body = get(site + path)
        assert 'href="/raw"' not in body
        assert "Raw Search" not in body
