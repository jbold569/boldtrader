"""Contract tests for the Chat API (ticket #42).

Session CRUD + the streaming chat turn over /api/v1/chat/. A live
ThreadingHTTPServer on an ephemeral port with a temp DB (BOLDTRADER_DB)
and a fake LLM callable swapped for `router.stream_chat` (prior art:
tests/test_chat_loop.py): the real model router is never touched.
Every assertion follows docs/api-contract.md: envelope shapes, JSON
error bodies, and `event: <name>\ndata: <json>\n\n` SSE framing.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.db import init_db

DRAFT = {
    "summary": "HP Z440 workstations, complete, <= $200",
    "product_identity": "HP Z440 workstation",
    "queries": ["HP Z440", "used HP Z440"],
    "exclusions": ["parts only"],
    "target_price": 200.0,
    "location": "Kenmore, WA",
}
DRAFT_TEXT = "Settled then.\n\n```json\n" + json.dumps(DRAFT) + "\n```"

DRAFT_KEYS = set(DRAFT)

# Exactly which data keys each BoldTrader event may carry — also proves
# no raw OpenAI fields (choices/delta/finish_reason) leak through.
SHAPES = {
    "token": {"text"},
    "reasoning": {"text"},
    "tool_call": {"name", "arguments"},
    "tool_result": {"name", "output", "chip"},
    "draft": DRAFT_KEYS,
    "turn_complete": {"session_id", "message"},
    "error": {"code", "message"},
}

WEB_RESULTS = [
    {"title": "HP Z440 on eBay", "href": "https://ebay.example/1", "body": "$180"},
    {"title": "HP Z440 review", "href": "https://review.example/1", "body": "great box"},
    {"title": "Z440 pricing guide", "href": "https://guide.example/1", "body": "$150-250 used"},
]


# --- fake router stream: OpenAI-format chunk dicts ------------------------


def d_reasoning(text: str) -> dict:
    return {"choices": [{"index": 0, "delta": {"reasoning_content": text}, "finish_reason": None}]}


def d_content(text: str) -> dict:
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}


def d_tool_call(index: int, id: str = None, name: str = None, arguments: str = None) -> dict:
    call = {"index": index}
    if id is not None:
        call["id"] = id
        call["type"] = "function"
    fn = {}
    if name is not None:
        fn["name"] = name
    if arguments is not None:
        fn["arguments"] = arguments
    if fn:
        call["function"] = fn
    return {"choices": [{"index": 0, "delta": {"tool_calls": [call]}, "finish_reason": None}]}


def d_finish(reason: str) -> dict:
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def make_fake_rounds(*rounds):
    """Each scripted round is a list of chunk dicts; one call = one round."""
    it = iter(rounds)

    def fake_stream(messages, tools=None, **kwargs):
        yield from next(it)

    return fake_stream


# --- fixtures -----------------------------------------------------------


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


@pytest.fixture
def fake_web_ok(monkeypatch):
    class FakeDDGS:
        def __init__(self, *a, **k):
            pass

        def text(self, query, **kwargs):
            return WEB_RESULTS

    monkeypatch.setattr("src.tools.DDGS", FakeDDGS)
    return WEB_RESULTS


def conn():
    return sqlite3.connect(os.environ["BOLDTRADER_DB"])


# --- http helpers --------------------------------------------------------


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def post_json(url: str, body) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def post_turn(base: str, session_id, message):
    """POST the turn body and read the whole SSE response (the fake never
    blocks, so a full read terminates)."""
    data = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/v1/chat/sessions/{session_id}/messages", data=data, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=10)
    body = resp.read().decode("utf-8")
    frames = []
    for chunk in body.split("\n\n"):
        if not chunk:
            continue
        lines = chunk.split("\n")
        assert len(lines) == 2, f"frame is not exactly event+data: {chunk!r}"
        assert lines[0].startswith("event: "), repr(lines[0])
        assert lines[1].startswith("data: "), repr(lines[1])
        name = lines[0][len("event: "):]
        payload = json.loads(lines[1][len("data: "):])
        frames.append({"event": name, "data": payload})
    return resp, frames


def assert_frame_shapes(frames):
    for f in frames:
        assert f["event"] in SHAPES, f"unknown event {f['event']!r}"
        expected = sorted(SHAPES[f["event"]])
        actual = sorted(f["data"])
        assert actual == expected, f"{f['event']} carries {actual}, expected {expected}"


def create_session(base: str, title: str = "test session") -> dict:
    status, session = post_json(base + "/api/v1/chat/sessions", {"title": title})
    assert status == 201
    return session


# --- session CRUD ---------------------------------------------------------


def test_create_session_with_title_returns_201(site):
    session = create_session(site, "My first chat")
    assert session["id"] == 1
    assert session["title"] == "My first chat"
    assert "T" in session["created_at"] and session["created_at"].endswith("Z")
    assert "T" in session["updated_at"] and session["updated_at"].endswith("Z")


def test_create_session_without_title(site):
    status, session = post_json(site + "/api/v1/chat/sessions", {})
    assert status == 201
    assert session["title"] == ""


def test_create_session_malformed_body_400(site):
    req = urllib.request.Request(
        site + "/api/v1/chat/sessions", data=b"not json", method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 400
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["error"]["code"] == "malformed_request"


def test_list_sessions_envelope(site):
    for i in range(3):
        create_session(site, f"session {i}")
    status, body = get_json(site + "/api/v1/chat/sessions")
    assert status == 200
    assert set(body) == {"items", "page", "per_page", "total", "total_pages"}
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["per_page"] == 50
    assert body["total_pages"] == 1
    for item in body["items"]:
        assert set(item) == {"id", "title", "created_at", "updated_at"}


def test_list_sessions_pagination(site):
    for i in range(5):
        create_session(site, f"s{i}")
    status, body = get_json(site + "/api/v1/chat/sessions?page=2&per_page=2")
    assert status == 200
    assert body["page"] == 2
    assert body["per_page"] == 2
    assert body["total"] == 5
    assert body["total_pages"] == 3
    assert len(body["items"]) == 2


def test_get_session_returns_persisted_messages(site):
    session = create_session(site)
    c = conn()
    c.execute(
        "INSERT INTO session_messages (chat_session_id, role, content) VALUES (?,?,?)",
        (session["id"], "user", "hello"),
    )
    c.execute(
        "INSERT INTO session_messages (chat_session_id, role, content) VALUES (?,?,?)",
        (session["id"], "assistant", "hi!"),
    )
    c.commit()
    c.close()
    status, got = get_json(f"{site}/api/v1/chat/sessions/{session['id']}")
    assert status == 200
    assert set(got) == {"id", "title", "messages"}
    assert got["id"] == session["id"]
    assert got["title"] == "test session"
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][0]["content"] == "hello"
    for m in got["messages"]:
        assert set(m) == {"role", "content", "created_at"}
        assert m["created_at"].endswith("Z")


def test_get_unknown_session_404(site):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_json(site + "/api/v1/chat/sessions/99")
    assert exc.value.code == 404
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["error"]["code"] == "chat_session_not_found"


def test_delete_session_204_then_get_404(site):
    session = create_session(site)
    req = urllib.request.Request(
        f"{site}/api/v1/chat/sessions/{session['id']}", method="DELETE"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 204
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_json(f"{site}/api/v1/chat/sessions/{session['id']}")
    assert exc.value.code == 404
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["error"]["code"] == "chat_session_not_found"


def test_delete_unknown_session_404(site):
    req = urllib.request.Request(site + "/api/v1/chat/sessions/99", method="DELETE")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 404


# --- the streaming turn ---------------------------------------------------


def test_turn_is_event_stream_content_type(site, monkeypatch):
    fake = make_fake_rounds([d_content("Hi."), d_finish("stop")])
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    resp, _ = post_turn(site, session["id"], "hello")
    assert resp.headers["Content-Type"].startswith("text/event-stream")


def test_plain_reply_emits_tokens_then_turn_complete(site, monkeypatch):
    fake = make_fake_rounds(
        [d_content("Hello"), d_content(" there"), d_finish("stop")]
    )
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    resp, frames = post_turn(site, session["id"], "hello")
    names = [f["event"] for f in frames]
    assert names == ["token", "token", "turn_complete"]
    assert frames[0]["data"] == {"text": "Hello"}
    assert frames[-1]["data"]["session_id"] == session["id"]
    assert frames[-1]["data"]["message"] == "Hello there"
    assert_frame_shapes(frames)


def test_user_message_persisted_before_streaming(site, monkeypatch):
    fake = make_fake_rounds([d_content("Reply."), d_finish("stop")])
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    post_turn(site, session["id"], "my first message")
    c = conn()
    rows = c.execute(
        "SELECT role, content FROM session_messages WHERE chat_session_id=? ORDER BY rowid",
        (session["id"],),
    ).fetchall()
    c.close()
    assert ("user", "my first message") in rows


def test_reasoning_deltas_become_reasoning_events(site, monkeypatch):
    fake = make_fake_rounds(
        [
            d_reasoning("Let me "),
            d_reasoning("think."),
            d_content("The answer."),
            d_finish("stop"),
        ]
    )
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    _, frames = post_turn(site, session["id"], "question")
    names = [f["event"] for f in frames]
    reasoning = [f["data"]["text"] for f in frames if f["event"] == "reasoning"]
    assert names[:2] == ["reasoning", "reasoning"]
    assert "".join(reasoning) == "Let me think."
    assert_frame_shapes(frames)


def test_tool_call_emits_tool_call_then_tool_result_with_chip(site, monkeypatch, fake_web_ok):
    tool_round = [
        d_tool_call(0, id="call_1", name="web_search", arguments=""),
        d_tool_call(0, arguments='{"query": '),
        d_tool_call(0, arguments='"hp z440"}'),
        d_finish("tool_calls"),
    ]
    final_round = [d_content("Found 3 good listings."), d_finish("stop")]
    fake = make_fake_rounds(tool_round, final_round)
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    _, frames = post_turn(site, session["id"], "search hp z440")
    names = [f["event"] for f in frames]
    assert names == [
        "tool_call",
        "tool_result",
        "token",
        "turn_complete",
    ]
    call = frames[0]["data"]
    assert call["name"] == "web_search"
    assert call["arguments"] == {"query": "hp z440"}
    result = frames[1]["data"]
    assert result["name"] == "web_search"
    assert "HP Z440 on eBay" in result["output"]
    assert result["chip"] == 'web_search: "hp z440" — 3 results'
    assert_frame_shapes(frames)
    # The tool round's rows are persisted so later turns can replay them.
    c = conn()
    roles = [
        r[0]
        for r in c.execute(
            "SELECT role FROM session_messages WHERE chat_session_id=? ORDER BY rowid",
            (session["id"],),
        ).fetchall()
    ]
    c.close()
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_draft_produces_draft_event_with_create_search_shape(site, monkeypatch):
    fake = make_fake_rounds(
        [d_content("Great.\n\n"), d_content("```json\n" + json.dumps(DRAFT) + "\n```"), d_finish("stop")]
    )
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    _, frames = post_turn(site, session["id"], "let's search z440s")
    names = [f["event"] for f in frames]
    assert names[-2:] == ["draft", "turn_complete"]
    draft = frames[-2]["data"]
    assert draft == DRAFT  # same shape as the create-search body
    assert frames[-1]["data"]["message"] == "Great."
    assert_frame_shapes(frames)


def test_mid_turn_failure_emits_error_event(site, monkeypatch):
    def fake_boom(messages, tools=None, **kwargs):
        yield d_content("So far so good")
        raise RuntimeError("router exploded")

    monkeypatch.setattr("src.router.stream_chat", fake_boom)
    session = create_session(site)
    resp, frames = post_turn(site, session["id"], "will it break?")
    assert frames[-1]["event"] == "error"
    assert frames[-1]["data"]["code"]
    assert frames[-1]["data"]["message"]
    assert_frame_shapes(frames)
    # The user message is already in the DB despite the failure.
    c = conn()
    rows = c.execute(
        "SELECT role, content FROM session_messages WHERE chat_session_id=? ORDER BY rowid",
        (session["id"],),
    ).fetchall()
    c.close()
    assert rows == [("user", "will it break?")]


def test_first_call_failure_emits_error_event_with_empty_stream_prefix(site, monkeypatch):
    def fake_boom(messages, tools=None, **kwargs):
        raise RuntimeError("router unreachable")

    monkeypatch.setattr("src.router.stream_chat", fake_boom)
    session = create_session(site)
    resp, frames = post_turn(site, session["id"], "hello?")
    assert [f["event"] for f in frames] == ["error"]
    assert_frame_shapes(frames)


def test_every_frame_parses_as_event_and_valid_json(site, monkeypatch):
    fake = make_fake_rounds(
        [
            d_reasoning("hm"),
            d_content("Answer with a draft.\n\n```json\n"),
            d_content(json.dumps(DRAFT) + "\n```"),
            d_finish("stop"),
        ]
    )
    monkeypatch.setattr("src.router.stream_chat", fake)
    session = create_session(site)
    body = post_turn(site, session["id"], "x")[1]
    assert body  # at least one frame
    assert_frame_shapes(body)


def test_turn_unknown_session_is_404_json(site):
    status, body = post_json(site + "/api/v1/chat/sessions/99/messages", {"message": "hi"})
    assert status == 404
    assert body["error"]["code"] == "chat_session_not_found"


def test_turn_missing_message_is_400(site):
    session = create_session(site)
    status, body = post_json(
        f"{site}/api/v1/chat/sessions/{session['id']}/messages", {}
    )
    assert status == 400
    assert body["error"]["code"] == "malformed_request"


def test_turn_malformed_body_is_400(site):
    session = create_session(site)
    req = urllib.request.Request(
        f"{site}/api/v1/chat/sessions/{session['id']}/messages",
        data=b"{oops",
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 400
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["error"]["code"] == "malformed_request"
