"""Ticket #70: Bulk price-refresh pass over live matched listings.

Fake-marketplace tests for the sweep-phase-B bulk pass: selection
(matched verdict, live availability, no Correction), 5s pacing, the
pass's own per-marketplace escalating cooldown (a blocked marketplace
never stalls the others), per-listing failure counting, and the
price-drop summary the digest consumes.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from src.db import init_db
from src.marketplace import ListingDetail, Marketplace, SearchResult
from src.pricerefresh import bulk_refresh_price


TODAY = date(2026, 11, 1)


class Boom(Exception):
    pass


class FakeClock:
    """time.monotonic/sleep stand-in that records sleeps and advances virtual time."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeMP(Marketplace):
    """Canned per-listing asks keyed by bare listing id; missing/error = failure."""

    name = "fake"

    def __init__(self, name="fake", details=None, error=None):
        self.name = name
        self._details = details or {}
        self._error = error

    def search(self, query, page=1, location=None) -> SearchResult:
        raise NotImplementedError

    def fetch_detail(self, listing) -> ListingDetail:
        if self._error is not None:
            raise self._error
        if listing.id not in self._details:
            raise Boom(f"no detail for {listing.id}")
        return self._details[listing.id]


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "bulk.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def seed_identity(conn, description="Dell OptiPlex 3060 Small Form Factor") -> int:
    cur = conn.execute(
        "INSERT INTO product_identities (description) VALUES (?)", (description,)
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid="offup:1", price=300.0, availability="live", pid=None) -> None:
    raw = json.dumps(
        {
            "id": lid.split(":", 1)[1],
            "title": "Dell Optiplex",
            "price": price,
            "condition": "used",
            "snippet": "works",
            "marketplace": lid.split(":", 1)[0],
        }
    )
    conn.execute(
        "INSERT INTO listings (id, raw, availability, product_identity_id) "
        "VALUES (?, ?, ?, ?)",
        (lid, raw, availability, pid),
    )
    conn.commit()


def seed_enrichment(conn, lid, condition="complete", corrected=0) -> None:
    conn.execute(
        "INSERT INTO enrichments (listing_id, condition, status, corrected) "
        "VALUES (?, ?, 'enriched', ?)",
        (lid, condition, corrected),
    )
    conn.commit()


def seed_search(conn, lids_verdicts, pid) -> int:
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, listing_ids, "
        "product_identity_id) VALUES ('s', 'p', ?, ?)",
        (json.dumps(lids_verdicts), pid),
    )
    conn.commit()
    return cur.lastrowid


def seed_board(conn, pid, dead_lids=(), corrected_lids=(), unsure_lids=(),
              match_lids=()) -> None:
    verdicts = {}
    for lid in match_lids:
        verdicts[lid] = "match"
    for lid in unsure_lids:
        verdicts[lid] = "unsure"
    for lid in dead_lids:
        verdicts[lid] = "match"
    for lid in corrected_lids:
        verdicts[lid] = "match"
    seed_search(conn, verdicts, pid)
    all_lids = list(match_lids) + list(unsure_lids) + list(dead_lids) + list(corrected_lids)
    for lid in all_lids:
        seed_listing(
            conn, lid=lid, price=300.0,
            availability="dead" if lid in dead_lids else "live",
            pid=pid,
        )
        seed_enrichment(conn, lid, corrected=1 if lid in corrected_lids else 0)


GOOD = ListingDetail(description="fine", price=300.0, shipping_cost=0.0)


# --- normal pass ----------------------------------------------------------


def test_normal_refreshes_only_matched_live_uncorrected(db):
    pid = seed_identity(db)
    seed_board(
        db, pid,
        match_lids=["ebay:1", "ebay:2", "ebay:3", "offup:4"],
        unsure_lids=["offup:5"],
        dead_lids=["dead:6"],
        corrected_lids=["corr:7"],
    )
    mp_e = FakeMP(name="ebay", details={"1": GOOD, "2": GOOD, "3": GOOD})
    mp_o = FakeMP(name="offup", details={"4": GOOD})
    clock = FakeClock()

    report = bulk_refresh_price(db, {"ebay": mp_e, "offup": mp_o}, clock=clock)

    assert report["refreshed_count"] == 4
    assert report["failed_count"] == 0
    body = json.dumps(report)
    # dead listing, corrected listing and unsure-only listing never touched
    assert "dead:6" not in body
    assert "corr:7" not in body
    assert "offup:5" not in body


def test_pacing_between_marketplace_calls(db):
    pid = seed_identity(db)
    seed_board(db, pid, match_lids=["ebay:1", "ebay:2", "ebay:3", "offup:4"])
    mp = FakeMP(details={
        "1": GOOD, "2": GOOD, "3": GOOD, "4": GOOD,
    })
    clock = FakeClock()

    bulk_refresh_price(db, {"ebay": mp, "offup": mp}, clock=clock)

    assert clock.sleeps == [5.0, 5.0, 5.0]  # between calls, not after the last


def test_price_drop_summary_top_three(db):
    pid = seed_identity(db)
    seed_board(db, pid, match_lids=["ebay:1", "ebay:2", "ebay:3", "offup:4"])
    # previous effective 300 each; three asks below, one above
    mp = FakeMP(details={
        "1": ListingDetail(description="d", price=200.0, shipping_cost=0.0),
        "2": ListingDetail(description="d", price=250.0, shipping_cost=0.0),
        "3": ListingDetail(description="d", price=150.0, shipping_cost=0.0),
        "4": ListingDetail(description="d", price=310.0, shipping_cost=0.0),
    })
    clock = FakeClock()

    report = bulk_refresh_price(db, {"ebay": mp, "offup": mp}, clock=clock)

    drops = report["price_drops"]
    assert drops["count"] == 3
    assert [d["listing_id"] for d in drops["top_3"]] == [
        "ebay:3", "ebay:1", "ebay:2",
    ]
    assert [d["amount"] for d in drops["top_3"]] == [150.0, 100.0, 50.0]


# --- blocked-marketplace pass ----------------------------------------------


def test_blocked_marketplace_cooldown_never_stalls_the_pass(db):
    pid = seed_identity(db)
    seed_board(
        db, pid,
        match_lids=["ebay:1", "ebay:2", "ebay:3"]
        + [f"offup:{i}" for i in range(4, 10)],
    )
    good = FakeMP(name="ebay", details={"1": GOOD, "2": GOOD, "3": GOOD})
    dead = FakeMP(name="offup", error=Boom("connection refused"))
    clock = FakeClock()

    report = bulk_refresh_price(db, {"ebay": good, "offup": dead}, clock=clock)

    # The healthy marketplace refreshed all of its listings; offup's first
    # five blocked fetches trip its cooldown (REFRESH_CONSECUTIVE_FAILURE_LIMIT),
    # and the sixth is skipped without a fetch attempt.
    assert report["refreshed_count"] == 3
    assert report["failed_count"] == 5
    assert report["blocked_marketplaces"] == {"offup": 1}


def test_cooldown_does_not_cool_a_healthy_marketplace(db):
    pid = seed_identity(db)
    seed_board(
        db, pid,
        match_lids=["ebay:1", "ebay:2", "ebay:3"]
        + [f"offup:{i}" for i in range(4, 10)],
    )
    good = FakeMP(name="ebay", details={"1": GOOD, "2": GOOD, "3": GOOD})
    dead = FakeMP(name="offup", error=Boom("connection refused"))
    clock = FakeClock()

    report = bulk_refresh_price(db, {"ebay": good, "offup": dead}, clock=clock)

    assert "ebay" not in report["blocked_marketplaces"]
    assert report["refreshed_count"] == 3


# --- all-fail pass ---------------------------------------------------------


def test_all_fail_pass_reports_every_failure(db):
    pid = seed_identity(db)
    seed_board(db, pid, match_lids=["ebay:1", "offup:2", "offup:3", "offup:4"])
    bad = FakeMP(error=Boom("all down"))
    clock = FakeClock()

    report = bulk_refresh_price(db, {"ebay": bad, "offup": bad}, clock=clock)

    assert report["refreshed_count"] == 0
    assert report["failed_count"] == 4
    assert report["price_drops"]["count"] == 0


# --- empty selection -------------------------------------------------------


def test_empty_selection_clean_report(db):
    seed_identity(db)
    clock = FakeClock()

    report = bulk_refresh_price(db, {}, clock=clock)

    assert report["refreshed_count"] == 0
    assert report["failed_count"] == 0
    assert report["price_drops"]["count"] == 0
    assert report["blocked_marketplaces"] == {}
    assert report["started_at"] < report["ended_at"]
