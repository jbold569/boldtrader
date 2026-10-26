"""Tests for Chat Session core (ticket #8).

Seams: chat session persistence + title generation (chat.py), the chat turn
loop with scripted FakeLLM turns, and route-level resume / specific-session
behavior against a live HTTP server on an ephemeral port with a temp DB.
The network is never touched: every model call and the fan-out are faked.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest

from src.db import init_db

DRAFT = {
    "summary": "HP Z440 workstations, complete, <= $200",
    "product_identity": "HP Z440 workstation",
    "queries": ["HP Z440", "used HP Z440"],
    "exclusions": ["parts only"],
    "target_price": 200,
    "location": "Kenmore, WA",
}
DRAFT_TEXT = "Settled then.\n\n```json\n" + json.dumps(DRAFT) + "\n```"

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


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB and no real marketplaces."""
    path = tmp_path / "site.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    init_db(path).close()

    from src import server as server_mod

    server_mod.Handler.marketplaces = {}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "all"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.read().decode("utf-8")


def post(url: str, form: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, data=urlencode(form).encode("utf-8"))
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


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


def test_get_chat_resumes_most_recent(site, monkeypatch):
    fake = FakeLLM(text_msg("First reply."), text_msg("Second reply."))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Title one")
    post(site + "/chat", {"message": "first message"})
    post(site + "/chat", {"message": "second message", "session_id": "1"})
    status, body = get(site + "/chat")
    assert status == 200
    assert 'name="session_id" value="1"' in body
    assert "first message" in body and "First reply." in body
    assert "second message" in body and "Second reply." in body


def test_get_chat_specific_session(site, monkeypatch):
    fake = FakeLLM(
        text_msg("Session one chat."),
        text_msg("Session two chat."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Title")
    post(site + "/chat", {"message": "one"})
    post(site + "/chat", {"message": "two"})
    status, body = get(site + "/chat?id=1")
    assert status == 200
    assert "Session one chat." in body
    assert "Session two chat." not in body
    assert 'name="session_id" value="1"' in body


def test_get_chat_unknown_session_404(site):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(site + "/chat?id=99")
    assert exc.value.code == 404


# --- route: POST /chat creates the session ------------------------------------

def test_first_message_creates_session_with_llm_title(site, monkeypatch):
    fake = FakeLLM(text_msg("I can help with that."))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Workstation research")
    status, body = post(site + "/chat", {"message": LONG_MESSAGE})
    assert status == 200
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    row = conn.execute("SELECT id, title FROM chat_sessions").fetchone()
    conn.close()
    assert row == (1, "Workstation research")
    assert 'name="session_id" value="1"' in body


def test_title_fallback_when_generation_fails(site, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("router down")

    fake = FakeLLM(text_msg("Fallback check."))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", boom)
    post(site + "/chat", {"message": LONG_MESSAGE})
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    title = conn.execute("SELECT title FROM chat_sessions WHERE id=1").fetchone()[0]
    conn.close()
    assert title == LONG_MESSAGE[:40]


def test_post_without_session_id_creates_a_new_session_even_when_one_exists(site, monkeypatch):
    fake = FakeLLM(text_msg("Reply one."), text_msg("Reply two."))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Title")
    post(site + "/chat", {"message": "seeding session"})
    # No session_id given ("New Chat"): a fresh session starts regardless.
    status, body = post(site + "/chat", {"message": "fresh start, no session_id given"})
    assert status == 200
    assert 'name="session_id" value="2"' in body
    # The new session's transcript is just this turn; session 1 keeps its own.
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    rows = conn.execute(
        "SELECT role, content FROM session_messages WHERE chat_session_id=2 ORDER BY rowid"
    ).fetchall()
    conn.close()
    assert rows == [
        ("user", "fresh start, no session_id given"),
        ("assistant", "Reply two."),
    ]


def test_model_failure_keeps_user_turn_rendered(site, monkeypatch):
    def boom(messages, **kwargs):
        raise RuntimeError("router down")

    monkeypatch.setattr("src.router.chat_with_tools", boom)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Title")
    status, body = post(site + "/chat", {"message": "will the model answer?"})
    assert status == 200
    assert "Model call failed (RuntimeError); try again." in body
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    rows = conn.execute(
        "SELECT role, content FROM session_messages WHERE chat_session_id=1 ORDER BY rowid"
    ).fetchall()
    conn.close()
    assert rows == [("user", "will the model answer?")]


# --- route: /confirm from a generic session -----------------------------------

def _confirm_body() -> dict:
    return {
        "summary": DRAFT["summary"],
        "product_identity": DRAFT["product_identity"],
        "queries": "\n".join(DRAFT["queries"]),
        "exclusions": "\n".join(DRAFT["exclusions"]),
        "target_price": "200",
        "location": "Kenmore, WA",
        "session_id": "1",
    }


def test_confirm_from_session_creates_search_and_starts_fanout(site, monkeypatch):
    fake = FakeLLM(text_msg(DRAFT_TEXT))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Title")
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "src.server.fan_out",
        lambda mkts, sid, loc: recorded.append((sid, loc)),
    )
    post(site + "/chat", {"message": "I want HP Z440 workstations under $200"})
    status, body = post(site + "/confirm", _confirm_body())
    assert status == 200
    assert "Bargain Search #1" in body
    deadline = time.time() + 2
    while time.time() < deadline and not recorded:
        time.sleep(0.01)
    assert recorded == [(1, "Kenmore, WA")]


def test_confirm_does_not_copy_transcript_into_conversations(site, monkeypatch):
    fake = FakeLLM(text_msg(DRAFT_TEXT))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    monkeypatch.setattr("src.router.chat", lambda *a, **k: "Title")
    monkeypatch.setattr("src.server.fan_out", lambda *a: None)
    post(site + "/chat", {"message": "I want HP Z440 workstations under $200"})
    post(site + "/confirm", _confirm_body())
    conn = sqlite3.connect(os.environ["BOLDTRADER_DB"])
    count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    search_count = conn.execute("SELECT COUNT(*) FROM bargain_searches").fetchone()[0]
    session_msgs = conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0]
    conn.close()
    assert count == 0  # nothing copied into the per-search conversations table
    assert search_count == 1
    assert session_msgs == 2  # the transcript lives on the session


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
