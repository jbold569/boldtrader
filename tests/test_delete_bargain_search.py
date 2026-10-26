"""Tests for the delete_bargain_search chat tool (ticket #11).

Seams: the tool surface (TOOL_SCHEMAS), the tool execution path in the
chat loop (next_reply with a scripted FakeLLM), and the delete guard on
the latest user message. Real sqlite (BOLDTRADER_DB temp file); the
network and the model are faked.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.db import init_db

DRAFT_A = {
    "summary": "Core i5-8400 mini PCs, complete, <= $150",
    "product_identity": "Core i5-8400 mini PC",
    "queries": ["i5-8400 mini", "small form factor"],
    "exclusions": ["parts only"],
    "target_price": 150,
    "location": "Kenmore, WA",
}
DRAFT_B = {
    "summary": "HP Z440 workstations, complete, <= $200",
    "product_identity": "HP Z440 workstation",
    "queries": ["HP Z440", "used HP Z440"],
    "exclusions": ["parts only"],
    "target_price": 200,
    "location": "Kenmore, WA",
}


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


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    conn = init_db(path)
    yield conn
    conn.close()


@pytest.fixture
def session(db):
    from src import chat as chat_mod

    return chat_mod.get_session(db, chat_mod.create_session(db, "delete test"))


def seed_two_searches(db):
    from src import chat as chat_mod

    id_a = chat_mod.create_search(db, DRAFT_A)
    id_b = chat_mod.create_search(db, DRAFT_B)
    return id_a, id_b


def search_row_exists(db, search_id) -> bool:
    row = db.execute(
        "SELECT 1 FROM bargain_searches WHERE id=?", (search_id,)
    ).fetchone()
    return row is not None


# --- registration -----------------------------------------------------------


def test_delete_tool_is_registered():
    from src import chat as chat_mod

    names = [s["function"]["name"] for s in chat_mod.TOOL_SCHEMAS]
    assert names == [
        "search_listings",
        "web_search",
        "get_listing",
        "delete_bargain_search",
    ]


def test_delete_schema_takes_exactly_one_id_no_list():
    from src import chat as chat_mod

    schema = next(
        s for s in chat_mod.TOOL_SCHEMAS
        if s["function"]["name"] == "delete_bargain_search"
    )["function"]["parameters"]
    assert list(schema["properties"]) == ["id"]
    assert schema["properties"]["id"]["type"] == "string"
    assert schema["required"] == ["id"]
    # no list/array variant anywhere in the tool surface (no bulk delete)
    for s in chat_mod.TOOL_SCHEMAS:
        props = s["function"]["parameters"]["properties"]
        assert not any(p.get("type") == "array" for p in props.values())


# --- accept path: user explicitly named the search ---------------------------


def test_delete_by_id_when_user_named_the_id(db, session, monkeypatch):
    from src import chat as chat_mod

    id_a, id_b = seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": str(id_a)})),
        text_msg("Deleted it."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    reply, _draft, _rows = chat_mod.next_reply(
        [],
        f"please delete bargain search {id_a}",
        conn=db,
        session_id=session["id"],
    )
    assert reply == "Deleted it."
    assert not search_row_exists(db, id_a)
    assert search_row_exists(db, id_b)  # only the named one is gone


def test_delete_echoes_summary_and_id(db, session, monkeypatch):
    from src import chat as chat_mod

    id_a, _id_b = seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": str(id_a)})),
        text_msg("Done."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    chat_mod.next_reply(
        [], f"delete {id_a} please", conn=db, session_id=session["id"]
    )
    tool_output = fake.calls[1]["messages"][-1]["content"]
    assert f"#{id_a}" in tool_output
    assert DRAFT_A["summary"] in tool_output
    assert "Deleted" in tool_output


def test_delete_by_exact_summary_when_id_not_given(db, session, monkeypatch):
    from src import chat as chat_mod

    id_a, id_b = seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": str(id_b)})),
        text_msg("Gone."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    chat_mod.next_reply(
        [],
        f'the search "{DRAFT_B["summary"]}" is useless, delete it',
        conn=db,
        session_id=session["id"],
    )
    assert not search_row_exists(db, id_b)
    assert search_row_exists(db, id_a)


def test_delete_also_removes_rejects_and_conversations(db, session, monkeypatch):
    from src import chat as chat_mod

    id_a, _id_b = seed_two_searches(db)
    from tests.test_tools import seed_full_listing

    seed_full_listing(db, "l1")
    db.execute(
        "INSERT INTO conversations (bargain_search_id, role, content) VALUES (?, 'user', 'x')",
        (id_a,),
    )
    db.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, 'l1', 'bad')",
        (id_a,),
    )
    db.commit()
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": str(id_a)})),
        text_msg("Done."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    chat_mod.next_reply(
        [], f"delete search {id_a}", conn=db, session_id=session["id"]
    )
    for table in ("conversations", "rejects"):
        n = db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE bargain_search_id=?", (id_a,)
        ).fetchone()[0]
        assert n == 0


# --- refuse path: user did not explicitly name the search --------------------


def test_refuse_when_search_not_named(db, session, monkeypatch):
    from src import chat as chat_mod

    id_a, id_b = seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": str(id_a)})),
        text_msg("Which one exactly?"),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    chat_mod.next_reply(
        [], "clean up some of my searches", conn=db, session_id=session["id"]
    )
    tool_output = fake.calls[1]["messages"][-1]["content"]
    assert tool_output == "Refused: the user did not explicitly name this search for deletion."
    assert search_row_exists(db, id_a)
    assert search_row_exists(db, id_b)


def test_refused_digit_does_not_match_inside_other_number(db, session, monkeypatch):
    from src import chat as chat_mod

    id_a, id_b = seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": str(id_a)})),
        text_msg("ok"),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    # user mentions "22" (search id 2 is a substring of 22, not a name)
    chat_mod.next_reply(
        [], "I paid 22 dollars for the last one", conn=db, session_id=session["id"]
    )
    assert search_row_exists(db, id_a)
    assert search_row_exists(db, id_b)


def test_unknown_id_not_found(db, session, monkeypatch):
    from src import chat as chat_mod

    seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": "99"})),
        text_msg("No such search."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    chat_mod.next_reply(
        [], "delete search 99", conn=db, session_id=session["id"]
    )
    tool_output = fake.calls[1]["messages"][-1]["content"]
    assert "99" in tool_output
    assert "not found" in tool_output.lower()


def test_non_numeric_id_is_invalid(db, session, monkeypatch):
    from src import chat as chat_mod

    seed_two_searches(db)
    fake = FakeLLM(
        tool_msg(tc("c1", "delete_bargain_search", {"id": "all"})),
        text_msg("Understood."),
    )
    monkeypatch.setattr("src.router.chat_with_tools", fake)

    chat_mod.next_reply(
        [], "delete search all of them", conn=db, session_id=session["id"]
    )
    tool_output = fake.calls[1]["messages"][-1]["content"]
    assert "Invalid" in tool_output
    assert search_row_exists(db, 1)
    assert search_row_exists(db, 2)


# --- system prompt ----------------------------------------------------------


def test_system_prompt_documents_fourth_tool_and_naming_rule():
    from src import chat as chat_mod

    assert "delete_bargain_search" in chat_mod.SYSTEM_PROMPT
    assert "explicitly" in chat_mod.SYSTEM_PROMPT
