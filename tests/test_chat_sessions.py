"""Tests for Chat Session core (ticket #8).

Seams: chat session persistence + title generation (chat.py) and the chat
turn loop with scripted FakeLLM turns, against a temp DB. The network is
never touched: every model call is faked.

Ticket #51 (M8) deleted the route-level tests in this file: they exercised
the legacy server-rendered /chat and /confirm pages. The JSON-API equivalents
live in tests/test_api_chat.py.
"""

from __future__ import annotations

import copy
import os

import pytest

from src.db import init_db

LONG_MESSAGE = "I have been looking around for a good used workstation lately and wonder what is out there"


def text_msg(content: str) -> dict:
    return {"role": "assistant", "content": content}


class FakeLLM:
    """Scripted assistant turns; records every call it receives."""

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, messages, **kwargs):
        self.calls.append(
            {"messages": copy.deepcopy(messages), "kwargs": copy.deepcopy(kwargs)}
        )
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self.responses.pop(0)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


# --- session persistence -----------------------------------------------------

def test_create_and_get_session(db):
    from src import chat as chat_mod

    sid = chat_mod.create_session(db, "My first chat")
    got = chat_mod.get_session(db, sid)
    assert got["id"] == sid
    assert got["title"] == "My first chat"


def test_get_session_missing_returns_none(db):
    from src import chat as chat_mod

    assert chat_mod.get_session(db, 99) is None


def test_latest_session_is_highest_id(db):
    from src import chat as chat_mod

    chat_mod.create_session(db, "first")
    second = chat_mod.create_session(db, "second")
    latest = chat_mod.latest_session(db)
    assert latest["id"] == second
    assert latest["title"] == "second"


def test_latest_session_none_when_empty(db):
    from src import chat as chat_mod

    assert chat_mod.latest_session(db) is None


def test_append_and_load_session_transcript(db):
    from src import chat as chat_mod

    sid = chat_mod.create_session(db, "t")
    chat_mod.append_session_message(db, sid, "user", "hello")
    chat_mod.append_session_message(db, sid, "assistant", "hi there")
    rows = chat_mod.load_session_transcript(db, sid)
    assert rows == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


# --- title generation --------------------------------------------------------

def test_generate_title_from_llm(monkeypatch):
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Used workstation hunting")
    from src import chat as chat_mod

    assert chat_mod.generate_title("looking for HP Z440 workstations") == "Used workstation hunting"


def test_generate_title_strips_quotes(monkeypatch):
    monkeypatch.setattr("src.router.chat", lambda *a, **k: '  "Desk deals"  ')
    from src import chat as chat_mod

    assert chat_mod.generate_title("any good desks?") == "Desk deals"


def test_generate_title_falls_back_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("router down")

    monkeypatch.setattr("src.router.chat", boom)
    from src import chat as chat_mod

    assert chat_mod.generate_title(LONG_MESSAGE) == LONG_MESSAGE[:40]


def test_generate_title_falls_back_on_empty(monkeypatch):
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "   ")
    from src import chat as chat_mod

    assert chat_mod.generate_title(LONG_MESSAGE) == LONG_MESSAGE[:40]


def test_system_prompt_is_generic_analysis_role():
    from src import chat as chat_mod

    lower = chat_mod.SYSTEM_PROMPT.lower()
    # The old authoring-only framing is gone.
    assert "search translator, not a purchase advisor" not in chat_mod.SYSTEM_PROMPT
    # Explicit never-invent / never-urge-buying guidance is present.
    assert "invent" in lower
    assert "never urge" in lower
    # May analyze deals and state math + fair-price confidence.
    assert "fair-price confidence" in lower
    assert "math" in lower


# --- turn loop persists to the session ----------------------------------------

def test_reply_turn_persists_to_session(db, monkeypatch):
    from src import chat as chat_mod

    fake = FakeLLM(text_msg("They run about $200."))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    sid = chat_mod.create_session(db, "t")
    reply, drafts, turn_rows = chat_mod.next_reply(
        [], "what should a used HP Z440 go for?", conn=db, session_id=sid
    )
    assert reply == "They run about $200."
    assert drafts == []
    assert turn_rows == [
        {"role": "user", "content": "what should a used HP Z440 go for?"},
        {"role": "assistant", "content": "They run about $200."},
    ]
    saved = chat_mod.load_session_transcript(db, sid)
    assert saved == turn_rows


def test_second_turn_appends_to_same_session(db, monkeypatch):
    from src import chat as chat_mod

    fake = FakeLLM(text_msg("Reply one."), text_msg("Reply two."))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    sid = chat_mod.create_session(db, "t")
    first = chat_mod.next_reply([], "one", conn=db, session_id=sid)
    chat_mod.next_reply(first[2], "two", conn=db, session_id=sid)
    saved = chat_mod.load_session_transcript(db, sid)
    assert [(r["role"], r["content"]) for r in saved] == [
        ("user", "one"),
        ("assistant", "Reply one."),
        ("user", "two"),
        ("assistant", "Reply two."),
    ]


def test_user_row_persisted_even_when_model_fails(db, monkeypatch):
    from src import chat as chat_mod

    sid = chat_mod.create_session(db, "t")

    def boom(messages, **kwargs):
        raise RuntimeError("router down")

    monkeypatch.setattr("src.router.chat_with_tools", boom)
    with pytest.raises(RuntimeError):
        chat_mod.next_reply([], "hello there", conn=db, session_id=sid)
    saved = chat_mod.load_session_transcript(db, sid)
    assert saved == [{"role": "user", "content": "hello there"}]


# --- existing conversations rows are untouched --------------------------------

def test_existing_conversations_rows_survive_init(db):
    db.execute(
        "INSERT INTO bargain_searches (summary, product_identity) VALUES ('old', 'old thing')"
    )
    db.execute(
        "INSERT INTO conversations (bargain_search_id, role, content) VALUES (1, 'user', 'legacy row')"
    )
    db.commit()
    init_db(os.environ["BOLDTRADER_DB"])  # idempotent re-init
    rows = db.execute("SELECT role, content FROM conversations").fetchall()
    assert rows == [("user", "legacy row")]
