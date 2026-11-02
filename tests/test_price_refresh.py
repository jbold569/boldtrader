"""Ticket #67: Price refresh for one stored live Listing.

Fake-marketplace unit tests: the frozen first-sight ask is replaced in the
stored row, a fresh Price Observation is computed through the shared
deal-math path, Corrections stand, and a fetch failure is reported
per-listing without touching stored data.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from src import dealmath
from src.db import init_db
from src.marketplace import ListingDetail, Marketplace, SearchResult
from src.pricerefresh import refresh_listing_price


TODAY = date(2026, 11, 1)


class FakeMarketplace(Marketplace):
    """Returns one canned detail, or raises, on every fetch_detail."""

    name = "offup"

    def __init__(self, detail=None, error=None):
        self._detail = detail
        self._error = error

    def search(self, query, page=1, location=None) -> SearchResult:
        raise NotImplementedError

    def fetch_detail(self, listing) -> ListingDetail:
        if self._error is not None:
            raise self._error
        return self._detail


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "refresh.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def seed_identity(conn, description) -> int:
    cur = conn.execute(
        "INSERT INTO product_identities (description) VALUES (?)", (description,)
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid="offup:1", price=400.0, shipping=None, pid=None):
    raw = json.dumps(
        {
            "id": lid.split(":", 1)[1],
            "title": "Desktop PC",
            "price": price,
            "marketplace": "offup",
            "url": "https://example.test/item",
        }
    )
    conn.execute(
        "INSERT INTO listings (id, raw, shipping_cost, product_identity_id) "
        "VALUES (?, ?, ?, ?)",
        (lid, raw, shipping, pid),
    )
    conn.commit()
    return lid


def seed_enrichment(conn, lid, condition="complete", bundle=None, corrected=0):
    conn.execute(
        "INSERT INTO enrichments (listing_id, condition, bundle, corrected, status) "
        "VALUES (?, ?, ?, ?, 'enriched')",
        (
            lid,
            condition,
            json.dumps(bundle) if bundle is not None else None,
            corrected,
        ),
    )
    conn.commit()


def add_obs(conn, iid, condition, price, days_ago=0, lid="offup:1"):
    observed = (TODAY - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO price_observations "
        "(listing_id, product_identity_id, condition, effective_price, observed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (lid, iid, condition, price, observed),
    )
    conn.commit()


def stored_listing(conn, lid="offup:1"):
    return conn.execute(
        "SELECT raw, shipping_cost, availability_checked_at FROM listings WHERE id=?",
        (lid,),
    ).fetchone()


# --- price moved ------------------------------------------------------------


def test_refresh_replaces_frozen_ask_and_shipping(db):
    pid = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    seed_listing(db, price=400.0, shipping=5.0, pid=pid)
    seed_enrichment(db, "offup:1")
    mp = FakeMarketplace(detail=ListingDetail(shipping_cost=15.0, price=250.0))
    result = refresh_listing_price(db, "offup:1", mp)
    assert result["status"] == "refreshed"
    assert result["asking_price"] == 250.0
    assert result["shipping_cost"] == 15.0
    assert result["effective_price"] == 265.0
    raw, shipping, checked_at = stored_listing(db)
    assert json.loads(raw)["price"] == 250.0
    assert shipping == 15.0
    assert checked_at is not None


def test_refresh_records_observation_with_flip_value(db):
    item_id = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    comp_id = seed_identity(db, "24 inch monitor")
    seed_listing(db, price=400.0, shipping=5.0, pid=item_id)
    for i in range(5):
        add_obs(db, comp_id, "complete", 80.0, days_ago=i)
    seed_enrichment(
        db,
        "offup:1",
        bundle=[{"description": "24 inch monitor", "confidence": "high"}],
    )
    mp = FakeMarketplace(detail=ListingDetail(shipping_cost=15.0, price=250.0))
    result = refresh_listing_price(db, "offup:1", mp)
    row = db.execute(
        "SELECT product_identity_id, condition, effective_price FROM price_observations "
        "WHERE listing_id='offup:1' AND product_identity_id=?",
        (item_id,),
    ).fetchone()
    assert row == (item_id, "complete", 185.0)


# --- price unchanged --------------------------------------------------------


def test_refresh_with_unchanged_ask_still_observes(db):
    pid = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    seed_listing(db, price=250.0, shipping=15.0, pid=pid)
    seed_enrichment(db, "offup:1")
    mp = FakeMarketplace(detail=ListingDetail(shipping_cost=15.0, price=250.0))
    result = refresh_listing_price(db, "offup:1", mp)
    assert result["status"] == "refreshed"
    assert result["effective_price"] == 265.0
    n = db.execute(
        "SELECT COUNT(*) FROM price_observations WHERE listing_id='offup:1'"
    ).fetchone()[0]
    assert n == 1


# --- corrections stand ------------------------------------------------------


def test_corrected_listing_is_skipped(db):
    pid = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    seed_listing(db, price=400.0, shipping=5.0, pid=pid)
    seed_enrichment(db, "offup:1", corrected=1)
    mp = FakeMarketplace(detail=ListingDetail(shipping_cost=15.0, price=250.0))
    result = refresh_listing_price(db, "offup:1", mp)
    assert result["status"] == "skipped_corrected"
    raw, shipping, checked_at = stored_listing(db)
    assert json.loads(raw)["price"] == 400.0
    assert shipping == 5.0
    assert checked_at is None
    n = db.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
    assert n == 0


# --- fetch failure ----------------------------------------------------------


def test_fetch_failure_is_reported_and_leaves_data_intact(db):
    pid = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    seed_listing(db, price=400.0, shipping=5.0, pid=pid)
    seed_enrichment(db, "offup:1")
    mp = FakeMarketplace(error=RuntimeError("connection reset"))
    result = refresh_listing_price(db, "offup:1", mp)
    assert result["status"] == "failed"
    assert "connection reset" in result["error"]
    raw, shipping, _ = stored_listing(db)
    assert json.loads(raw)["price"] == 400.0
    assert shipping == 5.0
    n = db.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
    assert n == 0


def test_missing_listing_is_reported_not_raised(db):
    mp = FakeMarketplace(detail=ListingDetail(price=1.0))
    result = refresh_listing_price(db, "offup:404", mp)
    assert result["status"] == "failed"
    assert "offup:404" in json.dumps(result)


def test_detail_without_ask_is_a_failure(db):
    pid = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    seed_listing(db, price=400.0, shipping=5.0, pid=pid)
    seed_enrichment(db, "offup:1")
    mp = FakeMarketplace(detail=ListingDetail(shipping_cost=15.0, price=None))
    result = refresh_listing_price(db, "offup:1", mp)
    assert result["status"] == "failed"
    raw, shipping, _ = stored_listing(db)
    assert json.loads(raw)["price"] == 400.0
    assert shipping == 5.0
    n = db.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
    assert n == 0


# --- fair price reflects the refresh -----------------------------------------


def test_fair_price_reflects_refreshed_observation(db):
    pid = seed_identity(db, "Dell OptiPlex 3060 Small Form Factor")
    seed_listing(db, price=400.0, shipping=5.0, pid=pid)
    seed_enrichment(db, "offup:1")
    for i, price in enumerate((300.0, 310.0, 290.0, 320.0)):
        add_obs(db, pid, "complete", price, days_ago=i)
    # Below the 5-observation minimum: no fair price yet.
    assert dealmath.fair_price(db, pid, "complete", as_of=TODAY) is None
    mp = FakeMarketplace(detail=ListingDetail(shipping_cost=15.0, price=190.0))
    refresh_listing_price(db, "offup:1", mp)
    fair = dealmath.fair_price(db, pid, "complete", as_of=TODAY)
    assert fair == 300.0  # median of 190, 290, 300, 310, 320
