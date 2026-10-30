"""Contract tests for the search-results JSON API (ticket #39).

Live ThreadingHTTPServer + urllib over a temp DB, in the style of
tests/test_api_searches.py. Covers GET /api/v1/searches/{id}/results
(verdict / max_price / availability filters, sort, all applied before
pagination) and the three per-search actions: rejections, reenrichment,
liveness. Data is seeded straight into SQLite; no marketplace, no model,
no fan-out.
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

API = "/api/v1/searches"

CARD_KEYS = {
    "listing_id",
    "title",
    "url",
    "asking_price",
    "marketplace",
    "image_url",
    "verdict",
    "verdict_stale",
    "availability",
    "authored_description",
    "enrichment",
}

ENRICHMENT_KEYS = {"status", "product", "condition", "bundle", "confidence"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB; nothing external."""
    path = tmp_path / "results.db"
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


@pytest.fixture
def db(tmp_path):
    """The same temp DB the server reads, for seeding and asserting."""
    conn = sqlite3.connect(str(tmp_path / "results.db"))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def call(method: str, url: str, body=None, raw: bytes | None = None):
    """One HTTP round-trip; returns (status, parsed_json_or_None, headers)."""
    data = raw if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else b""
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
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return exc.code, parsed, dict(exc.headers)


def seed_listing(
    conn,
    lid,
    price=100.0,
    marketplace="offerup",
    availability="live",
    first_seen="2026-10-01 00:00:00",
):
    """A listing row whose raw payload is shaped like the scrapers' Listing."""
    raw = {
        "id": lid,
        "title": f"Listing {lid}",
        "price": price,
        "condition": "used",
        "url": f"https://example.invalid/{lid}",
        "image_url": f"https://img.invalid/{lid}.jpg",
        "marketplace": marketplace,
    }
    conn.execute(
        "INSERT INTO listings (id, raw, availability, first_seen_at) VALUES (?, ?, ?, ?)",
        (lid, json.dumps(raw), availability, first_seen),
    )


def seed_enrichment(conn, lid, status="enriched"):
    product = {
        "description": "HP Z440, Xeon E5-2620 v3/16GB/512GB SSD",
        "action": "match",
        "matched_id": 1,
        "confidence": "high",
    }
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, bundle, "
        "confidence, status) VALUES (?, ?, ?, ?, ?, ?)",
        (
            lid,
            json.dumps(product),
            "complete",
            json.dumps([{"description": "keyboard", "confidence": "high"}]),
            json.dumps("high"),
            status,
        ),
    )


def seed_search(conn, verdicts, status="complete"):
    """A Bargain Search whose listing_ids carry the Sift verdicts."""
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status, "
        "listing_ids) VALUES ('test search', 'thing', ?, ?)",
        (status, json.dumps(verdicts)),
    )
    conn.commit()
    return cur.lastrowid


def results(site, search_id, query=""):
    status, body, _ = call("GET", f"{site}{API}/{search_id}/results{query}")
    assert status == 200, body
    return body


def ids(items):
    return [i["listing_id"] for i in items]


# --- verdict filter ----------------------------------------------------------


def test_default_verdict_is_match_and_unsure(db, site):
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    sid = seed_search(db, {"a": "match", "b": "unsure", "c": "not_match"})

    body = results(site, sid)

    assert set(ids(body["items"])) == {"a", "b"}
    assert body["total"] == 2


def test_verdict_single_value(db, site):
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    sid = seed_search(db, {"a": "match", "b": "unsure", "c": "not_match"})

    body = results(site, sid, "?verdict=match")

    assert ids(body["items"]) == ["a"]


def test_verdict_multiple_values(db, site):
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    sid = seed_search(db, {"a": "match", "b": "unsure", "c": "not_match"})

    body = results(site, sid, "?verdict=match,not_match")

    assert set(ids(body["items"])) == {"a", "c"}


def test_verdict_all_includes_everything(db, site):
    for lid in ("a", "b", "c"):
        seed_listing(db, lid)
    sid = seed_search(db, {"a": "match", "b": "unsure", "c": "not_match"})

    body = results(site, sid, "?verdict=all")

    assert set(ids(body["items"])) == {"a", "b", "c"}


def test_unknown_verdict_value_is_400(db, site):
    sid = seed_search(db, {})

    status, err, headers = call("GET", f"{site}{API}/{sid}/results?verdict=tasty")

    assert status == 400
    assert err["error"]["code"] == "invalid_verdict"
    assert "application/json" in headers.get("Content-Type", "")


# --- max_price filter --------------------------------------------------------


def test_max_price_drops_pricier_listings(db, site):
    seed_listing(db, "cheap", price=50.0)
    seed_listing(db, "mid", price=250.0)
    seed_listing(db, "dear", price=500.0)
    sid = seed_search(db, {k: "match" for k in ("cheap", "mid", "dear")})

    body = results(site, sid, "?max_price=250")

    assert set(ids(body["items"])) == {"cheap", "mid"}
    assert body["total"] == 2


def test_max_price_drops_listings_with_no_price(db, site):
    seed_listing(db, "priced", price=10.0)
    seed_listing(db, "free", price=None)
    sid = seed_search(db, {"priced": "match", "free": "match"})

    body = results(site, sid, "?max_price=100")

    assert ids(body["items"]) == ["priced"]


def test_max_price_garbage_is_400(db, site):
    sid = seed_search(db, {})

    status, err, _ = call("GET", f"{site}{API}/{sid}/results?max_price=cheap")

    assert status == 400
    assert err["error"]["code"] == "invalid_max_price"


# --- availability filter -----------------------------------------------------


def test_availability_filter(db, site):
    seed_listing(db, "alive", availability="live")
    seed_listing(db, "gone", availability="dead")
    sid = seed_search(db, {"alive": "match", "gone": "match"})

    live = results(site, sid, "?availability=live")
    dead = results(site, sid, "?availability=dead")

    assert ids(live["items"]) == ["alive"]
    assert ids(dead["items"]) == ["gone"]


def test_unknown_availability_is_400(db, site):
    sid = seed_search(db, {})

    status, err, _ = call("GET", f"{site}{API}/{sid}/results?availability=undead")

    assert status == 400
    assert err["error"]["code"] == "invalid_availability"


# --- combined filters, before pagination -------------------------------------


def test_filters_apply_before_pagination(db, site):
    # Newest first: m1, m2, m3 match; n1, n2 are not_match and must never show.
    rows = [
        ("m1", "2026-10-03 00:00:00"),
        ("n1", "2026-10-02 12:00:00"),
        ("m2", "2026-10-02 00:00:00"),
        ("n2", "2026-10-01 12:00:00"),
        ("m3", "2026-10-01 00:00:00"),
    ]
    for lid, seen in rows:
        seed_listing(db, lid, price=10.0, first_seen=seen)
    verdicts = {lid: ("match" if lid.startswith("m") else "not_match") for lid, _ in rows}
    sid = seed_search(db, verdicts)

    page1 = results(site, sid, "?verdict=match&per_page=2")
    page2 = results(site, sid, "?verdict=match&per_page=2&page=2")

    assert page1["total"] == 3
    assert page1["total_pages"] == 2
    assert ids(page1["items"]) == ["m1", "m2"]
    assert ids(page2["items"]) == ["m3"]


def test_max_price_and_availability_combine_with_paging(db, site):
    seed_listing(db, "keep", price=10.0, availability="live", first_seen="2026-10-05 00:00:00")
    seed_listing(db, "price_out", price=900.0, availability="live", first_seen="2026-10-04 00:00:00")
    seed_listing(db, "dead_out", price=10.0, availability="dead", first_seen="2026-10-06 00:00:00")
    sid = seed_search(db, {k: "match" for k in ("keep", "price_out", "dead_out")})

    page1 = results(site, sid, "?max_price=100&availability=live&per_page=1&page=1")
    page2 = results(site, sid, "?max_price=100&availability=live&per_page=1&page=2")

    assert page1["total"] == 1
    assert page1["total_pages"] == 1
    assert ids(page1["items"]) == ["keep"]
    assert page2["items"] == []


# --- sort --------------------------------------------------------------------


def test_sort_price_ascending(db, site):
    seed_listing(db, "mid", price=200.0)
    seed_listing(db, "low", price=50.0)
    seed_listing(db, "high", price=800.0)
    sid = seed_search(db, {k: "match" for k in ("mid", "low", "high")})

    body = results(site, sid, "?sort=price_asc")

    assert ids(body["items"]) == ["low", "mid", "high"]


def test_sort_price_descending(db, site):
    seed_listing(db, "mid", price=200.0)
    seed_listing(db, "low", price=50.0)
    seed_listing(db, "high", price=800.0)
    sid = seed_search(db, {k: "match" for k in ("mid", "low", "high")})

    body = results(site, sid, "?sort=price_desc")

    assert ids(body["items"]) == ["high", "mid", "low"]


def test_sort_newest_is_default(db, site):
    seed_listing(db, "old", first_seen="2026-09-01 00:00:00")
    seed_listing(db, "mid", first_seen="2026-10-01 00:00:00")
    seed_listing(db, "new", first_seen="2026-10-20 00:00:00")
    sid = seed_search(db, {k: "match" for k in ("old", "mid", "new")})

    default = results(site, sid)
    explicit = results(site, sid, "?sort=newest")

    assert ids(default["items"]) == ["new", "mid", "old"]
    assert ids(explicit["items"]) == ["new", "mid", "old"]


def test_unknown_sort_is_400(db, site):
    sid = seed_search(db, {})

    status, err, _ = call("GET", f"{site}{API}/{sid}/results?sort=sideways")

    assert status == 400
    assert err["error"]["code"] == "invalid_sort"


# --- pagination envelope -----------------------------------------------------


def test_results_pagination_envelope(db, site):
    for i in range(3):
        seed_listing(db, f"l{i}", price=10.0)
    sid = seed_search(db, {f"l{i}": "match" for i in range(3)})

    body = results(site, sid)

    assert body["page"] == 1
    assert body["per_page"] == 50
    assert body["total"] == 3
    assert body["total_pages"] == 1
    assert len(body["items"]) == 3


def test_results_per_page_capped_at_200(db, site):
    sid = seed_search(db, {})

    body = results(site, sid, "?per_page=500")

    assert body["per_page"] == 200


def test_results_bad_page_is_400(db, site):
    sid = seed_search(db, {})

    status, err, _ = call("GET", f"{site}{API}/{sid}/results?page=abc")

    assert status == 400
    assert err["error"]["code"] == "invalid_page"


# --- result-card shape -------------------------------------------------------


def test_result_card_shape(db, site):
    seed_listing(
        db,
        "offerup:1",
        price=250.0,
        marketplace="offerup",
        availability="live",
    )
    seed_enrichment(db, "offerup:1", status="enriched")
    sid = seed_search(db, {"offerup:1": "match"})

    card = results(site, sid)["items"][0]

    assert set(card) == CARD_KEYS
    assert card["listing_id"] == "offerup:1"
    assert card["title"] == "Listing offerup:1"
    assert card["url"] == "https://example.invalid/offerup:1"
    assert card["asking_price"] == 250.0
    assert card["marketplace"] == "offerup"
    assert card["image_url"] == "https://img.invalid/offerup:1.jpg"
    assert card["verdict"] == "match"
    assert card["availability"] == "live"
    assert card["authored_description"] is None
    assert set(card["enrichment"]) == ENRICHMENT_KEYS
    assert card["enrichment"]["status"] == "enriched"
    assert card["enrichment"]["product"] == {
        "description": "HP Z440, Xeon E5-2620 v3/16GB/512GB SSD",
        "action": "match",
        "matched_id": 1,
        "confidence": "high",
    }
    assert card["enrichment"]["condition"] == "complete"
    assert card["enrichment"]["bundle"] == [
        {"description": "keyboard", "confidence": "high"}
    ]
    assert card["enrichment"]["confidence"] == "high"


def test_enrichment_is_null_when_absent(db, site):
    seed_listing(db, "bare")
    sid = seed_search(db, {"bare": "match"})

    card = results(site, sid)["items"][0]

    assert card["enrichment"] is None


def test_authored_description_survives(db, site):
    seed_listing(db, "described")
    db.execute(
        "UPDATE listings SET authored_description='what it really is' WHERE id='described'"
    )
    sid = seed_search(db, {"described": "match"})

    card = results(site, sid)["items"][0]

    assert card["authored_description"] == "what it really is"


# --- rejections --------------------------------------------------------------


def test_rejection_returns_201_and_persists(db, site):
    seed_listing(db, "bad")
    sid = seed_search(db, {"bad": "match"})

    status, body, headers = call(
        "POST", f"{site}{API}/{sid}/rejections",
        {"listing_id": "bad", "reason": "wrong model"},
    )

    assert status == 201
    assert "application/json" in headers.get("Content-Type", "")
    rows = db.execute(
        "SELECT listing_id, reason FROM rejects WHERE bargain_search_id=?", (sid,)
    ).fetchall()
    assert rows == [("bad", "wrong model")]
    exclusions = json.loads(
        db.execute("SELECT exclusions FROM bargain_searches WHERE id=?", (sid,)).fetchone()[0]
    )
    assert exclusions == ["wrong model"]


def test_rejection_drops_the_listing_from_results(db, site):
    seed_listing(db, "keep")
    seed_listing(db, "toss")
    sid = seed_search(db, {"keep": "match", "toss": "match"})

    call("POST", f"{site}{API}/{sid}/rejections",
        {"listing_id": "toss", "reason": "nope"})

    assert set(ids(results(site, sid)["items"])) == {"keep"}


def test_rejection_of_existing_reason_does_not_duplicate_exclusion(db, site):
    seed_listing(db, "x")
    sid = seed_search(db, {"x": "match"})

    call("POST", f"{site}{API}/{sid}/rejections", {"listing_id": "x", "reason": "too big"})
    call("POST", f"{site}{API}/{sid}/rejections", {"listing_id": "x", "reason": "too big"})

    exclusions = json.loads(
        db.execute("SELECT exclusions FROM bargain_searches WHERE id=?", (sid,)).fetchone()[0]
    )
    assert exclusions == ["too big"]


def test_rejection_missing_fields_is_400(site):
    status, err, _ = call("POST", f"{site}{API}/1/rejections", {"listing_id": "x"})
    assert status == 400
    assert err["error"]["code"] == "invalid_rejection"


def test_rejection_malformed_body_is_400(site):
    status, err, _ = call("POST", f"{site}{API}/1/rejections", raw=b"{oops")
    assert status == 400
    assert err["error"]["code"] == "malformed_request"


def test_rejection_unknown_search_is_404(db, site):
    seed_listing(db, "orphan")

    status, err, _ = call(
        "POST", f"{site}{API}/999/rejections",
        {"listing_id": "orphan", "reason": "whatever"},
    )

    assert status == 404
    assert err["error"]["code"] == "search_not_found"


# --- reenrichment ------------------------------------------------------------


def test_reenrichment_returns_requeued_count_201(db, site):
    seed_listing(db, "missing")
    seed_listing(db, "broken")
    db.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES ('broken', 'failed')"
    )
    sid = seed_search(db, {"missing": "match", "broken": "unsure"})

    status, body, headers = call("POST", f"{site}{API}/{sid}/reenrichment")

    assert status == 201
    assert body == {"requeued": 2}
    rows = dict(db.execute("SELECT listing_id, status FROM enrichments").fetchall())
    assert rows == {"missing": "pending", "broken": "pending"}


def test_reenrichment_leaves_enriched_rows_untouched(db, site):
    seed_listing(db, "done")
    seed_enrichment(db, "done", status="enriched")
    sid = seed_search(db, {"done": "match"})

    status, body, _ = call("POST", f"{site}{API}/{sid}/reenrichment")

    assert status == 201
    assert body == {"requeued": 0}
    row = db.execute(
        "SELECT status FROM enrichments WHERE listing_id='done'"
    ).fetchone()
    assert row[0] == "enriched"


def test_reenrichment_unknown_search_is_404(site):
    status, err, _ = call("POST", f"{site}{API}/999/reenrichment")
    assert status == 404
    assert err["error"]["code"] == "search_not_found"


# --- liveness ----------------------------------------------------------------


def test_liveness_shape(site):
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    sid = seed_search(conn, {})
    conn.close()

    status, body, headers = call("GET", f"{site}{API}/{sid}/liveness")

    assert status == 200
    assert set(body) == {"done", "banner", "dead"}
    assert body["done"] is True
    assert body["banner"] == ""
    assert body["dead"] == []
    assert "application/json" in headers.get("Content-Type", "")


def test_liveness_unknown_search_is_404(site):
    status, err, _ = call("GET", f"{site}{API}/999/liveness")
    assert status == 404
    assert err["error"]["code"] == "search_not_found"


# --- error bodies ------------------------------------------------------------


def test_error_bodies_are_json_not_html(site):
    status, err, headers = call("GET", f"{site}{API}/999/results")

    assert status == 404
    assert set(err["error"]) == {"code", "message"}
    assert "text/html" not in headers.get("Content-Type", "")
    assert "<html" not in json.dumps(err).lower()
