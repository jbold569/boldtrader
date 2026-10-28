"""Contract tests for ad-hoc Marketplace search + Listing patch (ticket #40).

Live ThreadingHTTPServer + urllib over a temp DB, in the style of
tests/test_api_searches.py. Fake marketplaces only: the network and the
model are never touched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.db import init_db
from src.marketplace import Listing, Marketplace, SearchResult

SEARCH_URL = "/api/v1/marketplace/search"
LISTINGS = "/api/v1/listings"

CARD_KEYS = {"id", "title", "url", "asking_price", "marketplace", "image_url"}


class FakeMarketplace(Marketplace):
    """Echo marketplace: a page of N canned listings."""

    name = "fake"

    def __init__(self, n: int = 2) -> None:
        self.n = n
        self.calls: list[tuple] = []

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        self.calls.append((query, page, location))
        listings = [
            Listing(
                id=f"{self.name}:{page}:{i}",
                title=f"{query} item {i}",
                price=100.0 + i,
                image_url=f"https://img.example/{self.name}/{page}/{i}.jpg",
                url=f"https://{self.name}.example/listing/{page}/{i}",
            )
            for i in range(self.n)
        ]
        return SearchResult(
            listings=listings, total_results=self.n, page=page, page_size=self.n
        )


class RaisingMarketplace(Marketplace):
    """Simulates a marketplace outage."""

    name = "broken"

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        raise RuntimeError("marketplace down")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB and fake marketplaces."""
    path = tmp_path / "api.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    for i in (1, 2):
        conn.execute(
            "INSERT INTO listings (id, raw, availability) VALUES (?, '{}', 'live')",
            (f"offerup:{i}",),
        )
    conn.commit()
    conn.close()

    from src import server as server_mod

    one = FakeMarketplace(n=2)
    one.name = "one"
    two = FakeMarketplace(n=3)
    two.name = "two"
    server_mod.Handler.marketplaces = {"one": one, "two": two}
    server_mod.Handler.fanout_marketplaces = {"one": one, "two": two}
    server_mod.Handler.default_market = "one"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(method: str, url: str, body=None, raw: bytes | None = None):
    """One HTTP round-trip; returns (status, parsed_json_or_None, headers)."""
    data = raw if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else None
    )
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else None), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = text
        return exc.code, parsed, dict(exc.headers)


def db():
    return sqlite3.connect(os.environ["BOLDTRADER_DB"])


# --- GET /api/v1/marketplace/search ----------------------------------------


def test_search_happy_envelope(site):
    status, body, _ = call("GET", f"{site}{SEARCH_URL}?q=hp+z440")
    assert status == 200
    for key in ("items", "page", "per_page", "total", "total_pages", "failed_marketplaces"):
        assert key in body
    assert body["page"] == 1
    assert len(body["items"]) == 2
    assert body["failed_marketplaces"] == []
    card = body["items"][0]
    assert set(card) == CARD_KEYS
    assert card["asking_price"] == 100.0
    assert card["marketplace"] == "one"


def test_search_defaults_to_server_default_marketplace(site):
    status, body, _ = call("GET", f"{site}{SEARCH_URL}?q=hp+z440")
    assert status == 200
    assert {c["marketplace"] for c in body["items"]} == {"one"}


def test_search_explicit_marketplace(site):
    status, body, _ = call("GET", f"{site}{SEARCH_URL}?q=dell&marketplace=two")
    assert status == 200
    assert {c["marketplace"] for c in body["items"]} == {"two"}


def test_search_all_fans_across_marketplaces(site):
    status, body, _ = call("GET", f"{site}{SEARCH_URL}?q=dell&marketplace=all")
    assert status == 200
    assert {c["marketplace"] for c in body["items"]} == {"one", "two"}
    assert len(body["items"]) == 5


def test_search_partial_failure_reported_not_fatal(site):
    from src import server as server_mod

    server_mod.Handler.marketplaces = {"one": FakeMarketplace(n=2), "broken": RaisingMarketplace()}
    status, body, _ = call("GET", f"{site}{SEARCH_URL}?q=dell&marketplace=all")
    assert status == 200
    assert body["failed_marketplaces"] == ["broken"]
    assert len(body["items"]) == 2
    assert all(c["marketplace"] == "one" for c in body["items"])


def test_search_passes_page_and_location_through(site):
    status, body, _ = call(
        "GET", f"{site}{SEARCH_URL}?q=dell&marketplace=one&location=Kenmore%2C+WA&page=3"
    )
    assert status == 200
    assert body["page"] == 3
    from src import server as server_mod

    assert server_mod.Handler.marketplaces["one"].calls[-1] == ("dell", 3, "Kenmore, WA")


def test_search_invalid_page_rejected(site):
    status, body, _ = call("GET", f"{site}{SEARCH_URL}?q=dell&page=abc")
    assert status == 400
    assert body["error"]["code"]


# --- PATCH /api/v1/listings/{id} --------------------------------------------


def test_patch_authored_description(site):
    status, body, _ = call(
        "PATCH", f"{site}{LISTINGS}/offerup:1", body={"authored_description": "bare GPU only"}
    )
    assert status == 200
    assert set(body) == {"id", "authored_description", "availability"}
    assert body["id"] == "offerup:1"
    assert body["authored_description"] == "bare GPU only"
    assert body["availability"] == "live"
    conn = db()
    assert conn.execute(
        "SELECT authored_description FROM listings WHERE id='offerup:1'"
    ).fetchone()[0] == "bare GPU only"
    assert conn.execute(
        "SELECT status FROM enrichments WHERE listing_id='offerup:1'"
    ).fetchone()[0] == "pending"
    conn.close()


def test_patch_requeues_even_if_already_enriched(site):
    conn = db()
    conn.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES ('offerup:2', 'enriched')"
    )
    conn.commit()
    conn.close()
    status, body, _ = call(
        "PATCH", f"{site}{LISTINGS}/offerup:2", body={"authored_description": "with RAM"}
    )
    assert status == 200
    conn = db()
    assert conn.execute(
        "SELECT status FROM enrichments WHERE listing_id='offerup:2'"
    ).fetchone()[0] == "pending"
    conn.close()


def test_patch_empty_description_clears(site):
    call("PATCH", f"{site}{LISTINGS}/offerup:1", body={"authored_description": "text"})
    status, body, _ = call(
        "PATCH", f"{site}{LISTINGS}/offerup:1", body={"authored_description": ""}
    )
    assert status == 200
    assert body["authored_description"] is None
    conn = db()
    assert conn.execute(
        "SELECT authored_description FROM listings WHERE id='offerup:1'"
    ).fetchone()[0] is None
    conn.close()


def test_patch_unknown_listing_404(site):
    status, body, _ = call(
        "PATCH", f"{site}{LISTINGS}/nope:999", body={"authored_description": "x"}
    )
    assert status == 404
    assert body["error"]["code"] == "listing_not_found"


def test_patch_malformed_json_400(site):
    status, body, _ = call("PATCH", f"{site}{LISTINGS}/offerup:1", raw=b"{not json")
    assert status == 400
    assert body["error"]["code"] == "malformed_request"


def test_patch_missing_field_400(site):
    status, body, _ = call("PATCH", f"{site}{LISTINGS}/offerup:1", body={"other": 1})
    assert status == 400
    assert body["error"]["code"] == "malformed_request"


def test_patch_non_string_description_400(site):
    status, body, _ = call(
        "PATCH", f"{site}{LISTINGS}/offerup:1", body={"authored_description": 42}
    )
    assert status == 400
    assert body["error"]["code"] == "malformed_request"
