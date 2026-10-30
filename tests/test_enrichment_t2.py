"""T2 enrichment shape: identity resolution, mint-vs-match, typed bundle.

Schema validation for the new enrichment record (ticket #53) plus the
mint/match/unknown persistence path through ``fanout._enrich_one`` with a
faked router — the real model is never called here.
"""

from __future__ import annotations

import json

import pytest

from src import router
from src.db import init_db
from src.marketplace import ListingDetail
from src.router import RouterError, _validate_enrichment


def valid_record(**overrides):
    record = {
        "product": {
            "description": "Dell OptiPlex 3060, i5-8500/8GB/256GB SSD",
            "action": "match",
            "matched_id": 1,
            "confidence": "high",
        },
        "condition": "complete",
        "bundle": [
            {"description": "power cord", "confidence": "high"},
            {"description": "monitor stand", "confidence": "low"},
        ],
    }
    record.update(overrides)
    return record


def product_with(**overrides):
    product = {
        "description": "Dell OptiPlex 3060, i5-8500/8GB/256GB SSD",
        "action": "match",
        "matched_id": 1,
        "confidence": "high",
    }
    product.update(overrides)
    return {
        "product": product,
        "condition": "complete",
        "bundle": [{"description": "power cord", "confidence": "high"}],
    }


# --- _validate_enrichment: new shape --------------------------------------


def test_accepts_valid_record():
    assert _validate_enrichment(valid_record()) == valid_record()


def test_accepts_empty_bundle():
    _validate_enrichment(valid_record(bundle=[]))


def test_accepts_unknown_product():
    _validate_enrichment(
        valid_record(
            product={
                "description": "unknown",
                "action": "unknown",
                "matched_id": None,
                "confidence": "unknown",
            }
        )
    )


def test_rejects_missing_product():
    with pytest.raises(RouterError):
        _validate_enrichment({"condition": "complete", "bundle": []})


def test_rejects_non_dict_product():
    with pytest.raises(RouterError):
        _validate_enrichment(valid_record(product="Dell OptiPlex"))


def test_rejects_empty_description():
    record = valid_record()
    record["product"]["description"] = "   "
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_bad_action():
    record = valid_record()
    record["product"]["action"] = "create"
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_match_without_matched_id():
    record = valid_record()
    del record["product"]["matched_id"]
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_match_with_null_matched_id():
    record = valid_record()
    record["product"]["matched_id"] = None
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_match_with_string_matched_id():
    record = valid_record()
    record["product"]["matched_id"] = "one"
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_mint_with_matched_id():
    record = valid_record()
    record["product"]["action"] = "mint"
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_unknown_with_matched_id():
    record = valid_record()
    record["product"]["action"] = "unknown"
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_bad_product_confidence():
    record = valid_record()
    record["product"]["confidence"] = "certain"
    with pytest.raises(RouterError):
        _validate_enrichment(record)


def test_rejects_bad_condition():
    with pytest.raises(RouterError):
        _validate_enrichment(valid_record(condition="like new"))


def test_rejects_non_list_bundle():
    with pytest.raises(RouterError):
        _validate_enrichment(valid_record(bundle="keyboard"))


def test_rejects_bare_string_bundle_items():
    with pytest.raises(RouterError):
        _validate_enrichment(valid_record(bundle=["keyboard"]))


def test_rejects_bundle_item_missing_description():
    with pytest.raises(RouterError):
        _validate_enrichment(valid_record(bundle=[{"confidence": "high"}]))


def test_rejects_bundle_item_missing_confidence():
    with pytest.raises(RouterError):
        _validate_enrichment(valid_record(bundle=[{"description": "keyboard"}]))


def test_rejects_bundle_item_bad_confidence():
    with pytest.raises(RouterError):
        _validate_enrichment(
            valid_record(bundle=[{"description": "keyboard", "confidence": "sure"}])
        )


# --- enrich(): prompt carries candidates + buyer's note --------------------


def test_candidate_identities_reach_the_prompt(monkeypatch):
    captured = {}

    def fake_chat(messages, model, max_tokens):
        captured["messages"] = messages
        return json.dumps(valid_record())

    monkeypatch.setattr(router, "_chat", fake_chat)
    router.enrich(
        "some listing text",
        candidates=[{"id": 7, "description": "Dell OptiPlex 3060"}],
    )
    user = captured["messages"][1]["content"]
    assert "7: Dell OptiPlex 3060" in user
    assert "some listing text" in user


def test_authored_note_reaches_the_prompt(monkeypatch):
    captured = {}

    def fake_chat(messages, model, max_tokens):
        captured["messages"] = messages
        return json.dumps(valid_record())

    monkeypatch.setattr(router, "_chat", fake_chat)
    router.enrich("listing text", authored="actually has 32GB RAM", candidates=[])
    assert "actually has 32GB RAM" in captured["messages"][1]["content"]


def test_system_prompt_tells_model_to_trust_the_buyers_note():
    assert "buyer" in router._ENRICH_SYSTEM.lower()


# --- mint-vs-match persistence through _enrich_one -------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t2.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


class GoodMP:
    def fetch_detail(self, listing):
        return ListingDetail(description="a desktop computer")


def seed_pending(conn, lid="test:1", authored=""):
    raw = json.dumps(
        {
            "id": "1",
            "title": "Dell desktop",
            "price": 50.0,
            "condition": "used",
            "snippet": "works",
            "marketplace": "test",
        }
    )
    conn.execute(
        "INSERT INTO listings (id, raw, authored_description) VALUES (?, ?, ?)",
        (lid, raw, authored),
    )
    conn.execute(
        "INSERT INTO enrichments (listing_id, status) VALUES (?, 'pending')", (lid,)
    )
    conn.commit()


def run_enrich(db, record, monkeypatch, lid="test:1"):
    import src.fanout as fanout

    calls = []

    def fake_enrich(text, candidates=None, authored="", model=None):
        calls.append({"candidates": candidates, "authored": authored})
        return record

    monkeypatch.setattr(fanout.router, "enrich", fake_enrich)
    return fanout._enrich_one(db, {"test": GoodMP()}, lid), calls


def test_match_points_listing_at_existing_identity(db, monkeypatch):
    seed_pending(db)
    db.execute(
        "INSERT INTO product_identities (id, description) VALUES (1, 'Dell OptiPlex 3060')"
    )
    db.commit()
    ok, _ = run_enrich(db, product_with(), monkeypatch)
    assert ok is True
    row = db.execute("SELECT product_identity_id FROM listings WHERE id='test:1'").fetchone()
    assert row[0] == 1


def test_confident_mint_creates_identity_and_points_listing(db, monkeypatch):
    seed_pending(db)
    record = product_with(
        description="Herman Miller Aeron size B",
        action="mint",
        matched_id=None,
        confidence="high",
    )
    ok, _ = run_enrich(db, record, monkeypatch)
    assert ok is True
    rows = db.execute("SELECT id, description FROM product_identities").fetchall()
    assert rows == [(1, "Herman Miller Aeron size B")]
    row = db.execute("SELECT product_identity_id FROM listings WHERE id='test:1'").fetchone()
    assert row[0] == 1


def test_low_confidence_mint_never_mints(db, monkeypatch):
    seed_pending(db)
    record = product_with(action="mint", matched_id=None, confidence="low")
    ok, _ = run_enrich(db, record, monkeypatch)
    assert ok is True
    assert db.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0] == 0
    row = db.execute("SELECT product_identity_id FROM listings WHERE id='test:1'").fetchone()
    assert row[0] is None


def test_unknown_never_mints(db, monkeypatch):
    seed_pending(db)
    record = product_with(
        description="unknown", action="unknown", matched_id=None, confidence="unknown"
    )
    ok, _ = run_enrich(db, record, monkeypatch)
    assert ok is True
    assert db.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0] == 0
    row = db.execute("SELECT product_identity_id FROM listings WHERE id='test:1'").fetchone()
    assert row[0] is None


def test_match_with_nonexistent_id_leaves_listing_unidentified(db, monkeypatch):
    seed_pending(db)
    ok, _ = run_enrich(db, product_with(matched_id=99), monkeypatch)
    assert ok is True
    row = db.execute("SELECT product_identity_id FROM listings WHERE id='test:1'").fetchone()
    assert row[0] is None


def test_enrichment_row_stores_new_shape(db, monkeypatch):
    seed_pending(db)
    db.execute(
        "INSERT INTO product_identities (id, description) VALUES (1, 'Dell OptiPlex 3060')"
    )
    db.commit()
    run_enrich(db, product_with(), monkeypatch)
    row = db.execute(
        "SELECT product, condition, bundle, status FROM enrichments WHERE listing_id='test:1'"
    ).fetchone()
    assert json.loads(row[0]) == product_with()["product"]
    assert row[1] == "complete"
    assert json.loads(row[2]) == [{"description": "power cord", "confidence": "high"}]
    assert row[3] == "enriched"


def test_candidates_are_fetched_from_the_db(db, monkeypatch):
    seed_pending(db)
    db.execute("INSERT INTO product_identities (id, description) VALUES (5, 'Thing A')")
    db.execute("INSERT INTO product_identities (id, description) VALUES (6, 'Thing B')")
    db.commit()
    _, calls = run_enrich(db, product_with(), monkeypatch)
    assert calls[0]["candidates"] == [
        {"id": 5, "description": "Thing A"},
        {"id": 6, "description": "Thing B"},
    ]


def test_authored_override_wins_over_model_output(db, monkeypatch):
    seed_pending(db, authored="Herman Miller Aeron size B, graphite")
    model_record = product_with(
        description="Something else entirely",
        action="match",
        matched_id=1,
        confidence="high",
    )
    ok, calls = run_enrich(db, model_record, monkeypatch)
    assert ok is True
    assert calls[0]["authored"] == "Herman Miller Aeron size B, graphite"
    product = json.loads(
        db.execute("SELECT product FROM enrichments WHERE listing_id='test:1'")
        .fetchone()[0]
    )
    assert product == {
        "description": "Herman Miller Aeron size B, graphite",
        "matched_id": None,
        "action": "mint",
        "confidence": "high",
    }
    rows = db.execute("SELECT id, description FROM product_identities").fetchall()
    assert rows == [(1, "Herman Miller Aeron size B, graphite")]
    row = db.execute("SELECT product_identity_id FROM listings WHERE id='test:1'").fetchone()
    assert row[0] == 1
