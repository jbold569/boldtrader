"""Tests for the chat tool loop (ticket #6).

A fake LLM callable stands in for the router: monkeypatching
`src.router.chat_with_tools` swaps the model out (chat.py looks it up on
the router module, so the patch is seen at call time). Web and store tools
run for real against a temp DB (BOLDTRADER_DB); the network is never touched.
"""

from __future__ import annotations

import copy
import json

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


def tc(id: str, name: str, args: dict) -> dict:
    return {
        "id": id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def text_msg(content: str) -> dict:
    return {"role": "assistant", "content": content}


def tool_msg(*calls: dict, content: str = "") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": list(calls)}


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


WEB_RESULTS = [
    {"title": "HP Z440 on eBay", "href": "https://ebay.example/1", "body": "$180"},
    {"title": "HP Z440 review", "href": "https://review.example/1", "body": "great box"},
    {"title": "Z440 pricing guide", "href": "https://guide.example/1", "body": "$150-250 used"},
]


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


@pytest.fixture
def fake_web_ok(monkeypatch):
    class FakeDDGS:
        def __init__(self, *a, **k):
            pass

        def text(self, query, **kwargs):
            return WEB_RESULTS

    monkeypatch.setattr("src.tools.DDGS", FakeDDGS)
    return WEB_RESULTS


@pytest.fixture
def session(db):
    from src import chat as chat_mod

    return chat_mod.get_session(db, chat_mod.create_session(db, "test session"))


def stored_rows(conn, sid):
    rows = conn.execute(
        "SELECT role, content FROM session_messages WHERE chat_session_id=? ORDER BY rowid",
        (sid,),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


# --- scenario (a): plain answer, no tool use — unchanged behavior ------------

def test_plain_answer_unchanged(monkeypatch):
    fake = FakeLLM(text_msg(DRAFT_TEXT))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    reply, draft, rows = chat_mod.next_reply([], "I want a used workstation")
    assert draft["product_identity"] == "HP Z440 workstation"
    assert draft["summary"] == DRAFT["summary"]
    assert reply == "Settled then."
    assert "```" not in reply
    # exactly the user turn + the assistant answer; no tool round
    assert rows == [
        {"role": "user", "content": "I want a used workstation"},
        {"role": "assistant", "content": "Settled then."},
    ]
    assert len(fake.calls) == 1


def test_plain_answer_without_draft_unchanged(monkeypatch):
    fake = FakeLLM(text_msg("What is your budget?"))
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    reply, draft, _rows = chat_mod.next_reply([], "looking for a PC")
    assert reply == "What is your budget?"
    assert draft is None
    assert len(fake.calls) == 1


# --- scenario (b): one tool round, then the answer ---------------------------

def test_one_tool_round_persists_and_answers(db, session, fake_web_ok, monkeypatch):
    fake = FakeLLM(
        tool_msg(tc("c1", "web_search", {"query": "used HP Z440 price"})),
        text_msg("They run about $150-250.\n\n```json\n" + json.dumps(DRAFT) + "\n```"),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    reply, draft, _rows = chat_mod.next_reply(
        [], "what should a used HP Z440 go for?", conn=db, session_id=session["id"]
    )
    assert draft["product_identity"] == "HP Z440 workstation"
    assert reply == "They run about $150-250."
    assert len(fake.calls) == 2
    # the tool round request carried the tools
    assert fake.calls[0]["kwargs"]["tools"] == chat_mod.TOOL_SCHEMAS
    # first tool result reached the model on the follow-up call
    follow = fake.calls[1]["messages"]
    assert follow[-1]["role"] == "tool"
    assert follow[-1]["tool_call_id"] == "c1"
    assert "$180" in follow[-1]["content"]
    # persisted: user, assistant-with-tool_calls (JSON), tool result, assistant
    rows = stored_rows(db, session["id"])
    assert [r["role"] for r in rows] == ["user", "assistant", "tool", "assistant"]
    stored_asst = json.loads(rows[1]["content"])
    assert stored_asst["tool_calls"][0]["function"]["name"] == "web_search"
    assert stored_asst["tool_calls"][0]["function"]["arguments"] == json.dumps(
        {"query": "used HP Z440 price"}
    )
    # chip data: name + query in the stored call, hit count derivable from output
    chip = chat_mod.chip_text("web_search", "used HP Z440 price", rows[2]["content"])
    assert "web_search" in chip
    assert "used HP Z440 price" in chip
    assert "3 results" in chip


def test_tool_round_ignores_content_in_that_round(db, monkeypatch):
    fake = FakeLLM(
        tool_msg(tc("c1", "search_listings", {"keyword": "z440"}), content="mid reply"),
        text_msg("final answer"),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    reply, draft, _rows = chat_mod.next_reply([], "have we seen any Z440s?")
    assert reply == "final answer"
    assert draft is None


# --- scenario (c): 3-round cap, 4th request has no tools --------------------

def test_three_round_cap_forces_answer_without_tools(db, session, fake_web_ok, monkeypatch):
    calls = [
        tool_msg(tc(f"c{i}", "search_listings", {"keyword": "z440"})) for i in range(3)
    ] + [text_msg("Forced final answer.")]
    fake = FakeLLM(*calls)
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    reply, draft, _rows = chat_mod.next_reply(
        [], "keep looking", conn=db, session_id=session["id"]
    )
    assert reply == "Forced final answer."
    assert len(fake.calls) == 4
    for i in range(3):
        assert fake.calls[i]["kwargs"]["tools"] == chat_mod.TOOL_SCHEMAS
    assert "tools" not in fake.calls[3]["kwargs"]
    # 3 tool rounds persisted: user + 3×(assistant JSON + tool) + final assistant
    rows = stored_rows(db, session["id"])
    assert [r["role"] for r in rows] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


# --- scenario (d): web_search fails inside the loop --------------------------

def test_tool_failure_flows_back_and_turn_completes(db, session, monkeypatch):
    class BoomDDGS:
        def __init__(self, *a, **k):
            pass

        def text(self, query, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr("src.tools.DDGS", BoomDDGS)
    fake = FakeLLM(
        tool_msg(tc("c1", "web_search", {"query": "hp z440 price"})),
        text_msg("Web is down; asking instead."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    reply, draft, _rows = chat_mod.next_reply(
        [], "what do Z440s cost?", conn=db, session_id=session["id"]
    )
    assert reply == "Web is down; asking instead."
    rows = stored_rows(db, session["id"])
    tool_row = rows[2]
    assert tool_row["role"] == "tool"
    assert tool_row["content"] == "web search unavailable"
    # the failure string reached the model on the follow-up call
    assert fake.calls[1]["messages"][-1]["content"] == "web search unavailable"


# --- reconstruction for model replay ---------------------------------------

def test_reconstruct_maps_tool_rows_to_tool_messages():
    from src import chat as chat_mod

    rows = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "content": "",
                    "tool_calls": [
                        tc("c1", "web_search", {"query": "a"}),
                        tc("c2", "search_listings", {"keyword": "b"}),
                    ],
                }
            ),
        },
        {"role": "tool", "content": "web out"},
        {"role": "tool", "content": "store out"},
        {"role": "assistant", "content": "done"},
    ]
    msgs = chat_mod.reconstruct_messages(rows)
    assert len(msgs) == 5
    a1 = msgs[1]
    assert a1["role"] == "assistant"
    assert a1["tool_calls"][0]["id"] == "c1"
    assert a1["tool_calls"][1]["id"] == "c2"
    t1 = msgs[2]
    assert t1["role"] == "tool"
    assert t1["tool_call_id"] == "c1"
    assert t1["content"] == "web out"
    t2 = msgs[3]
    assert t2["tool_call_id"] == "c2"
    assert msgs[4]["content"] == "done"


# --- replaying persisted rows continues the conversation --------------------

def test_reloaded_transcript_carries_tool_context(db, session, fake_web_ok, monkeypatch):
    fake = FakeLLM(
        tool_msg(tc("c1", "web_search", {"query": "z440 price"})),
        text_msg("About $200."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)
    from src import chat as chat_mod

    chat_mod.next_reply([], "what should a used HP Z440 go for?", conn=db, session_id=session["id"])
    # reload the saved transcript the way a re-opened page would
    saved = chat_mod.load_session_transcript(db, session["id"])
    fake2 = FakeLLM(text_msg("I already looked that up: $200."))
    monkeypatch.setattr("src.router.chat_with_tools", fake2)
    chat_mod.next_reply(saved, "and the warranty?", conn=db, session_id=session["id"])
    sent = fake2.calls[0]["messages"]
    # system + (user, asst-tools, tool-result, assistant) from the saved
    # transcript + the new user message
    assert sent[1] == {"role": "user", "content": "what should a used HP Z440 go for?"}
    assert sent[2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert sent[3]["role"] == "tool"
    assert "$180" in sent[3]["content"]
    assert sent[-1] == {"role": "user", "content": "and the warranty?"}


# --- chip text derivation ---------------------------------------------------

def test_chip_text_with_result_count():
    from src import chat as chat_mod

    out = "Title: a\n\nTitle: b\n\nTitle: c"
    assert chat_mod.chip_text("search_listings", "z440", out) == (
        'search_listings: "z440" — 3 results'
    )


def test_chip_text_no_results():
    from src import chat as chat_mod

    out = 'No results for "z440".'
    assert chat_mod.chip_text("search_listings", "z440", out) == (
        'search_listings: "z440" — no results'
    )


def test_chip_text_undecorated_when_count_not_derivable():
    from src import chat as chat_mod

    assert chat_mod.chip_text("web_search", "q", "web search unavailable") == (
        'web_search: "q"'
    )
    assert chat_mod.chip_text("web_search", "q", "") == 'web_search: "q"'
    assert chat_mod.chip_text("web_search", "", "") == "web_search"
