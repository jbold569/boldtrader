"""Contract tests for the global events stream (ticket #41).

Live ThreadingHTTPServer + urllib over a temp DB, in the style of
tests/test_api_searches.py. GET /api/v1/events is a long-lived
text/event-stream: `: ping` comment frames every 15 s, and the three
BoldTrader events (enrichment / liveness / search_complete) driven
through the normal background code paths (fake marketplaces + fake
model, never the real network). Framing per contract:
`event: <name>\ndata: <json>\n\n`.
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

import pytest

from src.db import init_db

EVENTS_URL = "/api/v1/events"

VALID_DRAFT = {
    "summary": "HP Z440 workstations under $300",
    "product_identity": "HP Z440",
    "queries": ["hp z440"],
    "exclusions": ["no monitor"],
    "target_price": 300.0,
    "location": "Kenmore, WA",
}


class FakeMarketplace:
    """One page of one deterministic listing per search call."""

    name = "fake"

    def search(self, query, page=1, location=None):
        from src.marketplace import Listing, SearchResult

        if page > 1:
            return SearchResult(
                listings=[], total_results=0, page=page, page_size=50, total_pages=1
            )
        return SearchResult(
            listings=[
                Listing(
                    id=f"{query}-1",
                    title="HP Z440 workstation",
                    price=150.0,
                    url=f"https://example.invalid/{query}",
                )
            ],
            total_results=1,
            page=1,
            page_size=50,
            total_pages=1,
        )

    def fetch_detail(self, listing):
        from src.marketplace import ListingDetail

        return ListingDetail(description="a detailed description", images=[])


def fake_sift_match(summary, product_identity, exclusions=None):
    return "match"


def fake_sift_no_match(summary, product_identity, exclusions=None):
    return "not_match"


def fake_enrich(text, candidates=None, authored=""):
    return {
        "product": {
            "description": "HP Z440 Workstation",
            "action": "mint",
            "matched_id": None,
            "confidence": "high",
        },
        "condition": "complete",
        "bundle": [{"description": "keyboard", "confidence": "high"}],
    }


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB, fake marketplaces,
    and a fake model. The network and the real router are never touched."""
    path = tmp_path / "events.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    init_db(path).close()

    import src.fanout as fanout_mod
    from src import server as server_mod

    monkeypatch.setattr(fanout_mod.router, "sift", fake_sift_match)
    monkeypatch.setattr(fanout_mod.router, "enrich", fake_enrich)

    server_mod.Handler.marketplaces = {"fake": FakeMarketplace()}
    server_mod.Handler.fanout_marketplaces = {"fake": FakeMarketplace()}
    server_mod.Handler.default_market = "fake"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def conn():
    return sqlite3.connect(os.environ["BOLDTRADER_DB"])


def seed_pending(c, lid):
    raw = json.dumps(
        {
            "id": lid.split(":", 1)[1],
            "title": "Dell Optiplex",
            "price": 50.0,
            "condition": "used",
            "snippet": "works",
            "marketplace": "fake",
        }
    )
    c.execute("INSERT OR IGNORE INTO listings (id, raw) VALUES (?, ?)", (lid, raw))
    c.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES (?, 'pending')", (lid,)
    )
    c.commit()


def drain(timeout=10.0):
    """Process pending enrichment rows with the same per-row code the real
    worker runs (``_enrich_one`` + the post-row ``_refresh_progress``),
    polling until the queue stays empty. Synchronous by design: no
    background thread outlives the test or pollutes another test's fakes.
    """
    import src.fanout as fanout_mod

    deadline = time.monotonic() + timeout
    idle = 0
    c = conn()
    try:
        while time.monotonic() < deadline:
            rows = c.execute(
                "SELECT listing_id FROM enrichments WHERE status='pending' LIMIT 50"
            ).fetchall()
            if not rows:
                idle += 1
                if idle >= 5:
                    return
                time.sleep(0.02)
                continue
            idle = 0
            for (lid,) in rows:
                fanout_mod._enrich_one(c, {"fake": FakeMarketplace()}, lid)
                for srow in c.execute(
                    "SELECT id FROM bargain_searches WHERE status='enriching'"
                ).fetchall():
                    fanout_mod._refresh_progress(c, srow[0])
    finally:
        c.close()


def read_frame(f):
    """Read one SSE frame. Comment frames (``: ping``) return None;
    event frames return ``{"event": name, "data": parsed}``."""
    name = None
    data = None
    while True:
        line = f.readline()
        if not line:
            raise AssertionError("stream closed before a full event frame")
        line = line.decode("utf-8")
        if line == "\n":
            if name is None:
                return None  # comment frame
            return {"event": name, "data": json.loads(data or "")}
        if line.startswith(":"):
            continue
        if line.startswith("event: "):
            name = line[len("event: "):].strip()
        elif line.startswith("data: "):
            data = line[len("data: "):].rstrip("\r\n")


def next_event(f, name, timeout=10.0):
    """Read frames until one carrying ``name`` arrives (pings are skipped)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = read_frame(f)
        if frame is not None and frame["event"] == name:
            return frame
    raise AssertionError(f"no {name!r} event within {timeout}s")


def open_events(base):
    req = urllib.request.Request(base + EVENTS_URL)
    return urllib.request.urlopen(req, timeout=10)


def post_json(url, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# --- stream basics ---------------------------------------------------------


def test_events_stream_opens_with_event_stream_content_type(site):
    f = open_events(site)
    assert f.headers["Content-Type"].startswith("text/event-stream")
    assert "Content-Length" not in f.headers  # endless stream, not a fixed body


def test_ping_interval_is_15_seconds_by_default():
    import src.events as events_mod

    assert events_mod.PING_INTERVAL_SECONDS == 15.0


def test_ping_comment_frame_arrives(site, monkeypatch):
    import src.events as events_mod

    monkeypatch.setattr(events_mod, "PING_INTERVAL_SECONDS", 0.25)
    f = open_events(site)
    # Two pings so one stray early line can't pass for a single tick.
    for _ in range(2):
        deadline = time.monotonic() + 5
        while True:
            line = f.readline()
            assert line, "stream closed before a comment frame"
            if line.startswith(b":"):
                break
            assert time.monotonic() < deadline, "no comment frame in time"


# --- routing ---------------------------------------------------------------


def test_post_events_is_404(site):
    status, body = post_json(site + EVENTS_URL, {})
    assert status == 404
    assert body["error"]["code"] == "not_found"


# --- enrichment events (real path: per-row enrichment code runs) -----------


def test_enrichment_success_emits_enriched_event(site):
    f = open_events(site)
    c = conn()
    seed_pending(c, "fake:hp-z440")
    c.close()
    drain()

    ev = next_event(f, "enrichment")
    assert ev["data"] == {"listing_id": "fake:hp-z440", "status": "enriched"}


def test_enrichment_failure_emits_failed_event(site, monkeypatch):
    import src.fanout as fanout_mod

    def boom_enrich(text, candidates=None, authored=""):
        raise RuntimeError("model exploded")

    f = open_events(site)
    c = conn()
    seed_pending(c, "fake:broken")
    c.close()
    monkeypatch.setattr(fanout_mod.router, "enrich", boom_enrich)
    drain()

    ev = next_event(f, "enrichment")
    assert ev["data"] == {"listing_id": "fake:broken", "status": "failed"}


# --- search_complete (fan-out drained) --------------------------------------


def test_search_completion_emits_search_complete(site):
    f = open_events(site)
    status, created = post_json(site + "/api/v1/searches", VALID_DRAFT)
    assert status == 201
    search_id = created["id"]
    drain()

    ev = next_event(f, "search_complete")
    assert ev["data"] == {"search_id": search_id, "match_count": 1}
    c = conn()
    row = c.execute(
        "SELECT status FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    c.close()
    assert row[0] == "complete"


def test_zero_match_search_completes_with_zero(site, monkeypatch):
    # Nothing matched, so there is no enrichment queue to drain; fan-out
    # itself completes the search and emits the event.
    import src.fanout as fanout_mod

    monkeypatch.setattr(fanout_mod.router, "sift", fake_sift_no_match)
    f = open_events(site)
    status, created = post_json(site + "/api/v1/searches", VALID_DRAFT)
    assert status == 201

    ev = next_event(f, "search_complete")
    assert ev["data"] == {"search_id": created["id"], "match_count": 0}


# --- liveness events --------------------------------------------------------


def test_liveness_sweep_emits_liveness_event(site):
    import src.liveness as liveness_mod

    c = conn()
    cur = c.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status, listing_ids) "
        "VALUES ('s', 'thing', 'complete', ?)",
        (json.dumps({"fake:a": "match", "fake:b": "match"}),),
    )
    search_id = cur.lastrowid
    c.execute(
        "INSERT INTO listings (id, raw) VALUES (?, ?)",
        ("fake:a", json.dumps({"id": "a", "marketplace": "fake",
                              "url": "https://example.invalid/a"})),
    )
    c.execute(
        "INSERT INTO listings (id, raw) VALUES (?, ?)",
        ("fake:b", json.dumps({"id": "b", "marketplace": "fake",
                              "url": "https://example.invalid/b"})),
    )
    c.commit()
    c.close()

    f = open_events(site)
    liveness_mod._CHECKERS["fake"] = lambda mp, data: liveness_mod.LIVE
    try:
        liveness_mod.start(search_id)
        ev = next_event(f, "liveness")
        assert ev["data"] == {
            "search_id": search_id, "done": True, "dead_count": 0, "banner": "",
        }
    finally:
        liveness_mod._CHECKERS.pop("fake", None)


# --- subscribers -----------------------------------------------------------


def test_two_concurrent_readers_get_the_same_event(site):
    f1 = open_events(site)
    f2 = open_events(site)
    c = conn()
    seed_pending(c, "fake:both")
    c.close()
    drain()

    assert next_event(f1, "enrichment")["data"]["listing_id"] == "fake:both"
    assert next_event(f2, "enrichment")["data"]["listing_id"] == "fake:both"


def test_reader_disconnect_does_not_break_the_other(site, monkeypatch):
    import src.events as events_mod

    # A short ping gives the doomed writer something to write, so its dead
    # socket surfaces (and unsubscribes) promptly instead of 15 s later.
    monkeypatch.setattr(events_mod, "PING_INTERVAL_SECONDS", 0.25)
    baseline = events_mod.subscriber_count()
    survivor = open_events(site)
    doomed = open_events(site)
    doomed.close()  # abrupt client disconnect

    c = conn()
    seed_pending(c, "fake:survivor")
    c.close()
    drain()
    ev = next_event(survivor, "enrichment")
    assert ev["data"]["listing_id"] == "fake:survivor"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and events_mod.subscriber_count() != baseline + 1:
        time.sleep(0.05)
    assert events_mod.subscriber_count() == baseline + 1
