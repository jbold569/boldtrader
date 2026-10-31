"""T9 — Identity-aware chat (ticket #60).

Two seams: the system prompt (does it explain the identity world?) and
`create_search` (does the draft's product_identity phrase resolve to an
existing Product Identity instead of minting a duplicate?). Real sqlite
(BOLDTRADER_DB temp file); the model is never involved.
"""

from __future__ import annotations

import pytest

from src.db import init_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t9.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


DRAFT = {
    "summary": "Dell workstations under $300",
    "product_identity": "Dell Optiplex 7080 i5-10500/16GB",
    "queries": ["dell optiplex 7080"],
    "exclusions": ["parts only"],
    "target_price": 300.0,
    "location": "Kenmore, WA",
}


# --- system prompt: the identity world ---------------------------------------


def test_prompt_explains_product_identity():
    from src import chat as chat_mod

    lower = chat_mod.SYSTEM_PROMPT.lower()
    assert "Product Identity" in chat_mod.SYSTEM_PROMPT
    assert "living" in lower


def test_prompt_explains_verdicts_including_unknown():
    from src import chat as chat_mod

    lower = chat_mod.SYSTEM_PROMPT.lower()
    assert "deal" in lower
    assert "no_deal" in lower
    assert "unknown" in lower
    assert "cold start" in lower


def test_prompt_explains_threshold_semantics():
    from src import chat as chat_mod

    lower = chat_mod.SYSTEM_PROMPT.lower()
    assert "threshold" in lower
    # below the fair price, override beats default, raise-only
    assert "fair price" in lower
    assert "override" in lower
    assert "never lowered" in lower


def test_prompt_keeps_old_guarantees():
    from src import chat as chat_mod

    lower = chat_mod.SYSTEM_PROMPT.lower()
    assert "search translator, not a purchase advisor" not in chat_mod.SYSTEM_PROMPT
    assert "invent" in lower
    assert "never urge" in lower
    assert "fair-price confidence" in lower
    assert "math" in lower
    assert "delete_bargain_search" in chat_mod.SYSTEM_PROMPT
    assert "explicitly" in chat_mod.SYSTEM_PROMPT


# --- create_search: resolve-or-propose ---------------------------------------


def test_create_search_resolves_existing_identity(db):
    from src import chat

    cur = db.execute(
        "INSERT INTO product_identities (description) VALUES (?)",
        (DRAFT["product_identity"],),
    )
    db.commit()
    existing_id = cur.lastrowid

    sid = chat.create_search(db, DRAFT)

    row = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] == existing_id
    # No duplicate identity was minted.
    assert db.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0] == 1


def test_create_search_proposes_new_identity(db):
    from src import chat

    sid = chat.create_search(db, DRAFT)

    row = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()
    assert row[0] is not None
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (row[0],)
    ).fetchone()[0]
    assert desc == DRAFT["product_identity"]
    assert db.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0] == 1


def test_second_search_same_phrase_resolves(db):
    from src import chat

    first = chat.create_search(db, DRAFT)
    second = chat.create_search(db, DRAFT)

    a = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (first,)
    ).fetchone()[0]
    b = db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (second,)
    ).fetchone()[0]
    assert a == b
    assert db.execute("SELECT COUNT(*) FROM product_identities").fetchone()[0] == 1
