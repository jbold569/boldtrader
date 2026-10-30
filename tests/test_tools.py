"""Tests for the chat tools: Listing Store search (ticket #3) and web search (ticket #4).

Pure-function tests against a temporary SQLite database created with the
repo's real schema init, selected via the BOLDTRADER_DB env override.
web_search tests stub the DDGS backend; the network is never touched.
"""

from __future__ import annotations

import json

import pytest

from src.db import init_db
from src.tools import get_listing, search_listings, web_search


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
        db, "a1",
        {"description": "Herman Miller Aeron size B", "action": "mint",
         "matched_id": None, "confidence": "high"},
        "excellent",
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


class FakeDDGS:
    def __init__(self, results=None, error=None):
        self._results = results if results is not None else []
        self._error = error

    def text(self, query, **kwargs):
        if self._error:
            raise self._error
        return self._results


def test_web_search_exception_degrades(monkeypatch):
    monkeypatch.setattr("src.tools.DDGS", lambda *a, **k: FakeDDGS(error=RuntimeError("boom")))
    assert web_search("anything") == "web search unavailable"


def test_web_search_zero_results(monkeypatch):
    monkeypatch.setattr("src.tools.DDGS", lambda *a, **k: FakeDDGS(results=[]))
    assert web_search("rare thing") == 'No results for "rare thing".'


def test_web_search_formats_three_results(monkeypatch):
    results = [
        {"title": f"Title {i}", "href": f"https://ex.com/{i}", "body": f"Snippet {i}"}
        for i in range(1, 4)
    ]
    monkeypatch.setattr("src.tools.DDGS", lambda *a, **k: FakeDDGS(results=results))
    out = web_search("hp z440 price")
    assert "1. Title 1\nURL: https://ex.com/1\nSnippet: Snippet 1" in out
    assert "3. Title 3" in out
    assert "4." not in out


def test_web_search_blank_query():
    assert web_search("   ") == "Query required."


# --- get_listing (ticket #10) ----------------------------------------------


def seed_full_listing(conn, lid="a1", availability="sold"):
    raw = json.dumps(
        {
            "id": lid,
            "title": "Dell OptiPlex micro i5-8500",
            "price": 120.0,
            "condition": "used",
            "snippet": "small form factor",
            "marketplace": "facebook",
        }
    )
    conn.execute(
        "INSERT INTO listings (id, raw, authored_description, availability) "
        "VALUES (?, ?, ?, ?)",
        (lid, raw, "tiny PC, boots fine", availability),
    )
    conn.commit()


def seed_full_enrichment(conn, lid="a1"):
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, bundle, "
        "confidence, status) VALUES (?, ?, ?, ?, ?, 'enriched')",
        (
            lid,
            json.dumps({
                "description": "Dell OptiPlex 3060, i5-8500/8GB/256GB",
                "action": "mint",
                "matched_id": None,
                "confidence": "high",
            }),
            "complete",
            json.dumps([
                {"description": "power cord", "confidence": "high"},
                {"description": "stand", "confidence": "low"},
            ]),
            json.dumps("high"),
        ),
    )
    conn.commit()


def test_get_listing_known_id_returns_full_record(db):
    seed_full_listing(db)
    seed_full_enrichment(db)
    out = get_listing("a1")
    assert "a1" in out
    assert "Dell OptiPlex micro i5-8500" in out          # raw title
    assert "120" in out                                  # raw price
    assert "small form factor" in out                     # raw snippet
    assert "tiny PC, boots fine" in out                   # authored description
    assert "sold" in out                                  # availability
    assert "OptiPlex 3060" in out                        # enrichment product
    assert "complete" in out                              # enrichment condition
    assert "power cord" in out                            # bundle
    assert "high" in out                                  # confidence


def test_get_listing_without_enrichment(db):
    seed_full_listing(db, lid="b2", availability="live")
    out = get_listing("b2")
    assert "b2" in out
    assert "tiny PC, boots fine" in out
    assert "Enrichment: none" in out


def test_get_listing_unknown_id_says_not_seen(db):
    seed_full_listing(db, lid="a1")
    out = get_listing("zzz-999")
    assert "not seen" in out
    assert "zzz-999" in out


def test_get_listing_blank_id(db):
    assert get_listing("  ") == "Listing id required."
