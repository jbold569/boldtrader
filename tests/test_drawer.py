"""Route-level tests for the hamburger side drawer (ticket #12).

Seams: chat.list_sessions (the session-browser data) and the drawer markup
rendered on every page (Home, Search, Chat, enhanced view) against a live
HTTP server on an ephemeral port with a temp DB. The network is never
touched: fan-out and the liveness sweep are faked.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest

from src.chat import create_session, list_sessions
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


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "unit.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface 3xx as an HTTPError to the caller


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.read().decode("utf-8")


def post(url: str, form: dict, opener=None) -> tuple[int, str, dict]:
    data = urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(req) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


def insert_sessions(n: int, base_title: str = "session") -> list[int]:
    """Insert n sessions with staggered updated_at; the last is most recent."""
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    ids = []
    for i in range(n):
        cur = conn.execute(
            "INSERT INTO chat_sessions (title, updated_at) VALUES (?, ?)",
            (f"{base_title} {i + 1}", f"2026-01-01 {10 + i // 60:02d}:{i % 60:02d}:00"),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def drawer_of(body: str) -> str:
    return body.split('id="drawer"', 1)[1].split("</aside>", 1)[0]


# --- list_sessions: the session-browser data ---------------------------------

def test_list_sessions_returns_most_recent_first(db):
    one = create_session(db, "first")
    two = create_session(db, "second")
    db.execute("UPDATE chat_sessions SET updated_at='2026-01-01 00:00:00' WHERE id=?", (one,))
    db.execute("UPDATE chat_sessions SET updated_at='2026-01-02 00:00:00' WHERE id=?", (two,))
    db.commit()
    sessions = list_sessions(db)
    assert [s["id"] for s in sessions] == [two, one]
    assert [s["title"] for s in sessions] == ["second", "first"]


def test_list_sessions_respects_limit(db):
    ids = insert_sessions(30)
    sessions = list_sessions(db, limit=20)
    assert len(sessions) == 20
    assert sessions[0]["id"] == ids[29]  # most recently updated first
    assert sessions[-1]["id"] == ids[10]  # the 10 oldest are dropped


def test_list_sessions_empty(db):
    assert list_sessions(db) == []


# --- Drawer on every page --------------------------------------------------

def _assert_drawer(body: str, path: str) -> None:
    assert 'id="menu-toggle"' in body, f"no hamburger button on {path}"
    assert 'aria-label="Open menu"' in body, f"no aria-label on {path}"
    assert 'aria-expanded="false"' in body, f"no aria-expanded on {path}"
    assert 'id="drawer"' in body, f"no drawer on {path}"
    assert ">Home</a>" in body
    assert ">Search</a>" in body
    assert ">Chat</a>" in body
    assert 'id="new-chat"' in body and 'href="/chat?new=1"' in body


def test_drawer_on_home(site):
    status, body = get(site + "/")
    assert status == 200
    _assert_drawer(body, "/")


def test_drawer_on_search(site):
    status, body = get(site + "/search?q=lamp")
    assert status == 200
    _assert_drawer(body, "/search")


def test_top_navbar_removed(site):
    for path in ("/", "/search?q=lamp", "/chat"):
        status, body = get(site + path)
        assert 'class="navbar"' not in body, f"navbar still present on {path}"
        assert ">New Search</a>" not in body  # old nav wording gone everywhere


def test_drawer_on_enhanced_view(site, monkeypatch):
    monkeypatch.setattr("src.server.fan_out", lambda *a: None)
    monkeypatch.setattr("src.liveness.start", lambda *a: None)
    opener = urllib.request.build_opener(_NoRedirect())
    status, _, headers = post(site + "/search", VALID_FORM, opener=opener)
    assert status == 303
    status, body = get(site + headers["Location"])
    assert status == 200
    _assert_drawer(body, headers["Location"])


# --- Drawer contents: the session browser ----------------------------------

def test_drawer_lists_sessions_with_title_and_link(site):
    insert_sessions(1, base_title="Bike deals")
    status, body = get(site + "/")
    drawer = drawer_of(body)
    assert 'href="/chat?id=1"' in drawer
    assert ">Bike deals 1</a>" in drawer


def test_drawer_session_order_newest_first(site):
    ids = insert_sessions(3, base_title="s")
    # Bump session 1 so it becomes the most recently touched.
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    conn.execute(
        "UPDATE chat_sessions SET updated_at='2026-02-01 00:00:00' WHERE id=?", (ids[0],)
    )
    conn.commit()
    conn.close()
    status, body = get(site + "/")
    hrefs = re.findall(r'href="/chat\?id=(\d+)"', drawer_of(body))
    assert hrefs == ["1", "3", "2"]


def test_drawer_capped_at_twenty_sessions(site):
    insert_sessions(25)
    status, body = get(site + "/")
    hrefs = re.findall(r'href="/chat\?id=(\d+)"', drawer_of(body))
    assert len(hrefs) == 20
    assert hrefs[0] == "25"  # most recent first
    assert "1" not in hrefs  # five oldest dropped


def test_session_title_escaped_in_drawer(site):
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    conn.execute("INSERT INTO chat_sessions (title) VALUES (?)", ('<script>"x" & </script>',))
    conn.commit()
    conn.close()
    status, body = get(site + "/")
    assert '<script>"x" & </script>' not in body
    assert "&lt;script&gt;" in body


# --- New Chat always starts fresh ------------------------------------------

def test_new_chat_param_renders_fresh_empty_chat(site):
    insert_sessions(2)  # sessions exist; ?new=1 must not resume one
    status, body = get(site + "/chat?new=1")
    assert status == 200
    assert "Tell me what you want to buy." in body  # empty transcript
    assert 'name="session_id" value=""' in body


# --- JS / CSS wiring ------------------------------------------------------

def test_app_js_wires_drawer():
    js = open("src/templates/app.js", encoding="utf-8").read()
    assert "menu-toggle" in js
    assert "drawer" in js
    assert "Escape" in js
    assert "aria-expanded" in js


def test_drawer_styles_use_theme_vars():
    css = open("src/templates/app.css", encoding="utf-8").read()
    drawer_css = css[css.index("#drawer"):][:800]
    for var in ("var(--card)", "var(--border)", "var(--fg)"):
        assert var in drawer_css, f"{var} missing from drawer styles"
