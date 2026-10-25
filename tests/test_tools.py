"""Tests for the Listing Store search tool (ticket #3).

Pure-function tests against a temporary SQLite database created with the
repo's real schema init, selected via the BOLDTRADER_DB env override.
"""

from __future__ import annotations

import json

import pytest

from src.db import init_db
from src.tools import search_listings


def seed_listing(conn, lid, title, price=100.0, condition="good", snippet=""):
    raw = json.dumps(
        {
            "id": lid,
            "title": title,
            "price": price,
            "condition": condition,
            "snippet": snippet,
            "marketplace": "facebook",
        }
    )
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, ?)", (lid, raw))


def seed_enrichment(conn, lid, product, condition):
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, status) "
        "VALUES (?, ?, ?, 'enriched')",
        (lid, json.dumps(product), condition),
    )


def seed_pending(conn, lid):
    conn.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES (?, 'pending')", (lid,)
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


def test_keyword_hits_title(db):
    seed_listing(db, "a1", "Herman Miller Aeron chair size B")
    db.commit()
    out = search_listings("aeron")
    assert "Herman Miller Aeron chair size B" in out


def test_search_is_case_insensitive(db):
    seed_listing(db, "a1", "Vintage Desk Lamp")
    db.commit()
    out = search_listings("DESK LAMP")
    assert "Vintage Desk Lamp" in out


def test_keyword_hits_raw_text_only(db):
    seed_listing(db, "a1", "Comfy chair", snippet="genuine leather, made in Italy")
    db.commit()
    out = search_listings("italy")
    assert "Comfy chair" in out


def test_enriched_hit_shows_resolved_product_and_condition(db):
    seed_listing(db, "a1", "office chair")
    seed_enrichment(
        db, "a1", {"manufacturer": "Herman Miller", "model": "Aeron", "config": "size B"}, "excellent"
    )
    db.commit()
    out = search_listings("office chair")
    assert "Enriched: Herman Miller Aeron size B, condition: excellent" in out
    assert "not enriched" not in out


def test_unenriched_hit_says_not_enriched(db):
    seed_listing(db, "a1", "office chair")
    seed_pending(db, "a1")  # queued, never enriched
    db.commit()
    out = search_listings("office chair")
    assert "not enriched" in out
    assert "Enriched:" not in out


def test_top_five_cap(db):
    for i in range(7):
        seed_listing(db, f"a{i}", f"match {i} item")
    db.commit()
    out = search_listings("match")
    assert out.count("not enriched") == 5
    assert "match 0" in out and "match 4" in out
    assert "match 6" not in out


def test_no_match_returns_clear_message(db):
    seed_listing(db, "a1", "office chair")
    db.commit()
    out = search_listings("elephant")
    assert "No results" in out


def test_empty_store_returns_clear_message(db):
    out = search_listings("anything")
    assert "No results" in out


def test_blank_keyword_gets_own_message(db):
    seed_listing(db, "a1", "office chair")
    db.commit()
    out = search_listings("   ")
    assert "Keyword required" in out
    assert "office chair" not in out
