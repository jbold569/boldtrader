"""Route-level tests for the enhanced-view Modify link and pre-filled
advanced form (ticket #13).

Modify replaces the old "Refine in Chat": the enhanced view links to
/search?id=N&modify=1, which opens the Search page with the advanced
Bargain Search form pre-filled; saving updates the stored search, bumps
its version, and redirects back to the enhanced view.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest

from src.chat import create_search
from src.db import init_db
from src.marketplace import Listing, Marketplace, SearchResult

DRAFT = {
    "summary": "HP Z228 workstations under $150",
    "product_identity": "HP Z228 workstation",
    "queries": ["HP Z228", "used HP Z228"],
    "exclusions": ["parts only"],
    "target_price": 150.0,
    "location": "Kenmore, WA",
}

UPDATED_FORM = {
    "search_id": "1",
    "summary": "HP Z230 workstations under $120",
    "product_identity": "HP Z230 workstation",
    "queries": "HP Z230\nused HP Z230",
    "exclusions": "broken only",
    "target_price": "120",
    "location": "Redmond, WA",
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


@pytest.fixture
def stored(site):
    """A search already in the DB (id 1)."""
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    try:
        create_search(conn, DRAFT)
    finally:
        conn.close()
    return site


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


# --- The Modify link on the enhanced view -------------------------------------

def test_enhanced_view_shows_modify_link(stored):
    status, body = get(stored + "/search?id=1")
    assert status == 200
    assert 'href="/search?id=1&modify=1">Modify</a>' in body


def test_no_refine_link_anywhere(stored):
    for path in ("/", "/searches", "/search", "/chat", "/search?id=1"):
        _, body = get(stored + path)
        assert "Refine in Chat" not in body
        assert "Refine in chat" not in body

def test_modify_unknown_search_falls_back_to_normal_search(site):
    status, body = get(site + "/search?id=999&modify=1")
    assert status == 200
    # the normal search page: raw search bar, form closed by default
    assert 'name="q"' in body
    assert '<div id="advanced" hidden>' in body


def test_modify_view_opens_advanced_form_prefilled(stored):
    status, body = get(stored + "/search?id=1&modify=1")
    assert status == 200
    # advanced section visible (no `hidden` attribute)
    assert '<div id="advanced">' in body
    # every stored field pre-filled
    assert 'value="HP Z228 workstations under $150"' in body
    assert 'value="HP Z228 workstation"' in body
    assert ">HP Z228\nused HP Z228<" in body
    assert ">parts only<" in body
    assert 'value="150.0"' in body
    assert 'value="Kenmore, WA"' in body
    # the form carries the id so saving updates this search
    assert '<input type="hidden" name="search_id" value="1">' in body


# --- POST /search with search_id: update, version bump, redirect ---------------

def test_save_modify_updates_search_and_bumps_version(stored):
    code, _, headers = post(stored + "/search", UPDATED_FORM, follow=False)
    assert code == 303
    assert headers["Location"] == "/search?id=1"
    row = db_rows(
        "SELECT summary, product_identity, queries, exclusions, target_price, "
        "location, version FROM bargain_searches WHERE id=1"
    )[0]
    assert row[0] == "HP Z230 workstations under $120"
    assert row[1] == "HP Z230 workstation"
    assert json.loads(row[2]) == ["HP Z230", "used HP Z230"]
    assert json.loads(row[3]) == ["broken only"]
    assert row[4] == 120.0
    assert row[5] == "Redmond, WA"
    assert row[6] == 2


def test_save_modify_does_not_create_a_new_search(stored):
    post(stored + "/search", UPDATED_FORM, follow=False)
    assert db_rows("SELECT COUNT(*) FROM bargain_searches")[0][0] == 1


def test_save_modify_kicks_fanout(stored, monkeypatch):
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "src.server.fan_out",
        lambda mkts, sid, loc: recorded.append((sid, loc)),
    )
    post(stored + "/search", UPDATED_FORM, follow=False)
    deadline = time.time() + 2
    while time.time() < deadline and not recorded:
        time.sleep(0.01)
    assert recorded == [(1, "Redmond, WA")]


def test_save_modify_empty_summary_filled_from_product_identity(stored):
    form = dict(UPDATED_FORM, summary="")
    post(stored + "/search", form, follow=False)
    assert db_rows("SELECT summary FROM bargain_searches WHERE id=1")[0][0] == (
        "HP Z230 workstation"
    )


def test_invalid_modify_save_rerenders_form_without_bumping_version(stored):
    form = {k: v for k, v in UPDATED_FORM.items() if k != "queries"}
    code, body, headers = post(stored + "/search", form, follow=False)
    assert code == 200  # no redirect
    assert "queries must be a non-empty list of strings" in body
    # version untouched
    assert db_rows("SELECT version FROM bargain_searches WHERE id=1")[0][0] == 1
    # edit stays open with the id preserved
    assert '<div id="advanced">' in body
    assert '<input type="hidden" name="search_id" value="1">' in body
