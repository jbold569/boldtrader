"""T3 deal-math tests (ticket #54): fair price and effective price per
ADR 0011. The stored deal threshold was deleted in ticket #61.

Deterministic fixtures only: identities, observations, and listings are
seeded by hand; the model router is never called live (the fan-out
integration fakes it the way ticket #53's tests do).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from src import dealmath
from src.db import init_db
from src.marketplace import ListingDetail


TODAY = date(2026, 10, 30)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "dealmath.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def day(days_ago: int) -> str:
    """ISO date string N days before the fixed TODAY."""
    return (TODAY - timedelta(days=days_ago)).isoformat()


def seed_listing(conn, lid="offup:1", price=310.0):
    raw = json.dumps(
        {"id": "1", "title": "Desktop", "price": price, "marketplace": "offup"}
    )
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, ?)", (lid, raw))
    conn.commit()
    return lid


def seed_identity(conn, description) -> int:
    cur = conn.execute(
        "INSERT INTO product_identities (description) VALUES (?)",
        (description,),
    )
    conn.commit()
    return cur.lastrowid


def add_obs(conn, iid, condition, price, observed_at, lid="offup:1"):
    conn.execute(
        "INSERT INTO price_observations "
        "(listing_id, product_identity_id, condition, effective_price, observed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (lid, iid, condition, price, observed_at),
    )
    conn.commit()


# --- observation recording ---------------------------------------------------


def test_record_observation_stores_one_row(db):
    seed_listing(db)
    iid = seed_identity(db, "Dell OptiPlex 3060")
    dealmath.record_observation(db, "offup:1", iid, "complete", 275.0, day(0))
    rows = db.execute("SELECT * FROM price_observations").fetchall()
    assert len(rows) == 1


# --- fair price --------------------------------------------------------------


def test_fair_price_is_median_of_trailing_observations(db):
    seed_listing(db)
    iid = seed_identity(db, "Dell OptiPlex 3060")
    for price in (100.0, 120.0, 110.0, 130.0, 140.0):
        add_obs(db, iid, "complete", price, day(1))
    assert dealmath.fair_price(db, iid, "complete", as_of=TODAY) == 120.0


def test_fair_price_none_below_five_observations_cold_start(db):
    seed_listing(db)
    iid = seed_identity(db, "Dell OptiPlex 3060")
    for price in (100.0, 120.0, 110.0, 130.0):
        add_obs(db, iid, "complete", price, day(1))
    assert dealmath.fair_price(db, iid, "complete", as_of=TODAY) is None


def test_fair_price_ignores_stale_observations_outside_90_days(db):
    seed_listing(db)
    iid = seed_identity(db, "Dell OptiPlex 3060")
    # Five observations from 100 days ago must not count toward the window.
    for price in (10.0, 20.0, 30.0, 40.0, 50.0):
        add_obs(db, iid, "complete", price, day(100))
    assert dealmath.fair_price(db, iid, "complete", as_of=TODAY) is None
    # Five fresh ones make the fair price from the fresh pool only.
    for price in (100.0, 110.0, 120.0, 130.0, 140.0):
        add_obs(db, iid, "complete", price, day(1))
    assert dealmath.fair_price(db, iid, "complete", as_of=TODAY) == 120.0


def test_fair_price_is_per_condition(db):
    seed_listing(db)
    iid = seed_identity(db, "Dell OptiPlex 3060")
    for price in (100.0, 110.0, 120.0, 130.0, 140.0):
        add_obs(db, iid, "complete", price, day(1))
    for price in (70.0, 80.0, 90.0, 75.0, 85.0):
        add_obs(db, iid, "for parts", price, day(1))
    assert dealmath.fair_price(db, iid, "complete", as_of=TODAY) == 120.0
    assert dealmath.fair_price(db, iid, "for parts", as_of=TODAY) == 80.0


# --- effective price ---------------------------------------------------------


def test_effective_price_adds_shipping_then_subtracts_flip_value():
    assert dealmath.effective_price(300.0, 10.0, 45.0) == 265.0


def test_effective_price_without_shipping_is_asking_minus_flip():
    assert dealmath.effective_price(300.0, None, 45.0) == 255.0


# --- flip value --------------------------------------------------------------


def test_flip_value_sums_fair_asks_of_resolvable_extras(db):
    kb = seed_identity(db, "Logitech K270 keyboard")
    seed_listing(db)
    for price in (30.0,) * 5:
        add_obs(db, kb, "complete", price, day(1))
    mon = seed_identity(db, "24 inch monitor")
    for price in (60.0,) * 5:
        add_obs(db, mon, "complete", price, day(1))
    bundle = [
        {"description": "Logitech K270 keyboard", "confidence": "high"},
        {"description": "24 inch monitor", "confidence": "high"},
    ]
    flip = dealmath.flip_value(
        db, bundle, "Dell OptiPlex 3060 i5-8500 8GB", as_of=TODAY
    )
    assert flip == 90.0


def test_flip_value_ignores_components_inside_the_identity_description(db):
    seed_listing(db)
    ram = seed_identity(db, "8GB RAM")
    for price in (25.0,) * 5:
        add_obs(db, ram, "complete", price, day(1))
    bundle = [{"description": "8GB RAM", "confidence": "high"}]
    flip = dealmath.flip_value(
        db, bundle, "Dell OptiPlex 3060 with 8gb RAM and 256GB SSD", as_of=TODAY
    )
    assert flip == 0.0


def test_flip_value_unresolvable_components_contribute_zero(db):
    seed_listing(db)
    # The component's identity exists but has no observations at all.
    ghost = seed_identity(db, "Mystery dock")
    bundle = [
        {"description": "Mystery dock", "confidence": "high"},
        {"description": "Nonexistent thing", "confidence": "low"},
    ]
    flip = dealmath.flip_value(db, bundle, "Dell OptiPlex 3060", as_of=TODAY)
    assert flip == 0.0


def test_flip_value_empty_bundle_is_zero(db):
    assert dealmath.flip_value(db, [], "Dell OptiPlex 3060", as_of=TODAY) == 0.0


def test_flip_value_accepts_legacy_bare_string_bundles(db):
    # Pre-#53 corpora stored bundles as bare strings. The reader must treat
    # each string as the component description, not crash.
    kb = seed_identity(db, "Logitech K270 keyboard")
    seed_listing(db)
    for price in (30.0,) * 5:
        add_obs(db, kb, "complete", price, day(3))
    bundle = ["Logitech K270 keyboard", "power cable"]
    flip = dealmath.flip_value(db, bundle, "Dell OptiPlex 3060 i5-8500", as_of=TODAY)
    assert flip == 30.0


# --- enrichment integration --------------------------------------------------


class FakeMP:
    def __init__(self, shipping):
        self._shipping = shipping

    def fetch_detail(self, listing):
        return ListingDetail(description="a desktop computer", shipping_cost=self._shipping)


def record(product, condition="complete", bundle=None):
    return {
        "product": {
            "description": product,
            "action": "mint",
            "matched_id": None,
            "confidence": "high",
        },
        "condition": condition,
        "bundle": bundle or [],
    }


def run_enrich(db, fake_record, monkeypatch, lid="offup:1", shipping=10.0):
    import src.fanout as fanout

    def fake_enrich(text, candidates=None, authored="", model=None):
        return fake_record

    monkeypatch.setattr(fanout.router, "enrich", fake_enrich)
    return fanout._enrich_one(db, {"offup": FakeMP(shipping)}, lid)


def test_successful_enrichment_records_a_price_observation(db, monkeypatch):
    seed_listing(db, price=310.0)
    kb = seed_identity(db, "usb keyboard")
    for _ in range(5):
        add_obs(db, kb, "complete", 45.0, day(1))
    ok = run_enrich(
        db,
        record(
            "Dell OptiPlex 3060 i5-8500 8GB",
            bundle=[{"description": "usb keyboard", "confidence": "high"}],
        ),
        monkeypatch,
    )
    assert ok is True
    row = db.execute(
        "SELECT product_identity_id, condition, effective_price FROM price_observations "
        "WHERE listing_id='offup:1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    # out-the-door 310 + 10 = 320, minus the 45 keyboard flip = 275.
    assert (row[1], row[2]) == ("complete", 275.0)
    assert row[0] != kb  # the freshly minted identity, not the keyboard's


def test_unresolved_listing_records_no_observation(db, monkeypatch):
    seed_listing(db, price=310.0)
    rec = {
        "product": {
            "description": "unknown",
            "action": "unknown",
            "matched_id": None,
            "confidence": "unknown",
        },
        "condition": "complete",
        "bundle": [],
    }
    assert run_enrich(db, rec, monkeypatch) is True
    assert db.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 0


def test_listing_without_price_records_no_observation(db, monkeypatch):
    raw = json.dumps({"id": "1", "title": "Desktop", "price": None, "marketplace": "offup"})
    conn = db
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, ?)", ("offup:1", raw))
    conn.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES (?, 'pending')", ("offup:1",)
    )
    conn.commit()
    assert run_enrich(db, record("Dell OptiPlex 3060"), monkeypatch) is True
    assert db.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 0
