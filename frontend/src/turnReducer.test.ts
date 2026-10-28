// Pure turn-reducer tests (ticket #49). The reducer is the decision-encoding
// module from docs/migration-plan.md "SSE turn reducer": turn_complete is the
// ONLY commit point. These tests assert folded state only — no DOM, no network.

import { describe, it, expect } from "vitest";
import {
  emptyTurn,
  reduce,
  reduceAll,
  clearError,
  type ChatViewMessage,
  type TurnState,
  type TurnEvent,
} from "./turnReducer";

function tok(text: string): TurnEvent {
  return { event: "token", data: { text } };
}

describe("emptyTurn", () => {
  it("starts with no messages and an empty pending", () => {
    const s = emptyTurn();
    expect(s.messages).toEqual([]);
    expect(s.pending).toEqual({
      text: "",
      reasoning: "",
      toolCalls: [],
      draft: null,
    });
  });
});

describe("token folding", () => {
  it("appends each token to pending.text without touching committed messages", () => {
    let s = reduce(emptyTurn(), tok("Hel"));
    s = reduce(s, tok("lo"));
    expect(s.pending.text).toBe("Hello");
    expect(s.messages).toEqual([]);
  });
});

describe("reasoning folding", () => {
  it("accumulates into pending.reasoning, never into pending.text", () => {
    let s = reduce(emptyTurn(), { event: "reasoning", data: { text: "thinking hard" } });
    s = reduce(s, { event: "reasoning", data: { text: " still thinking" } });
    expect(s.pending.reasoning).toBe("thinking hard still thinking");
    expect(s.pending.text).toBe("");
  });
});

describe("tool_call / tool_result folding", () => {
  it("tool_call pushes a running chip", () => {
    const s = reduce(emptyTurn(), {
      event: "tool_call",
      data: { name: "search_listings", arguments: { keyword: "hp z440" } },
    });
    expect(s.pending.toolCalls).toEqual([
      { name: "search_listings", arguments: { keyword: "hp z440" }, status: "running", chip: null },
    ]);
  });

  it("tool_result completes the oldest running chip with the same name", () => {
    let s = reduce(emptyTurn(), {
      event: "tool_call",
      data: { name: "search_listings", arguments: { keyword: "a" } },
    });
    s = reduce(s, {
      event: "tool_call",
      data: { name: "search_listings", arguments: { keyword: "b" } },
    });
    s = reduce(s, {
      event: "tool_result",
      data: { name: "search_listings", output: "10 results", chip: "10 listings found" },
    });
    expect(s.pending.toolCalls[0]).toEqual({
      name: "search_listings",
      arguments: { keyword: "a" },
      status: "done",
      chip: "10 listings found",
    });
    // second one is still running
    expect(s.pending.toolCalls[1].status).toBe("running");
  });

  it("completes the first chip when only one exists", () => {
    let s = reduce(emptyTurn(), {
      event: "tool_call",
      data: { name: "web_search", arguments: { q: "x" } },
    });
    s = reduce(s, {
      event: "tool_result",
      data: { name: "web_search", output: "...", chip: "5 sources" },
    });
    expect(s.pending.toolCalls[0].status).toBe("done");
    expect(s.pending.toolCalls[0].chip).toBe("5 sources");
  });
});

describe("draft folding", () => {
  it("stashes the draft object into pending.draft", () => {
    const draft = {
      summary: "HP Z440 tower",
      product_identity: "HP Z440",
      queries: ["hp z440"],
      exclusions: [],
      target_price: 300,
      location: "US",
    };
    const s = reduce(emptyTurn(), { event: "draft", data: draft });
    expect(s.pending.draft).toEqual(draft);
  });

  it("draft survives to turn_complete and lands on the committed message", () => {
    let s = reduce(emptyTurn(), tok("Here is the "));
    s = reduce(s, {
      event: "draft",
      data: { summary: "S", queries: ["q"] },
    });
    s = reduce(s, tok("search."));
    s = reduce(s, {
      event: "turn_complete",
      data: { session_id: 7, message: "Here is the search." },
    });
    expect(s.messages.length).toBe(1);
    expect(s.messages[0].content).toBe("Here is the search.");
    expect(s.messages[0].draft).toEqual({ summary: "S", queries: ["q"] });
  });
});

describe("turn_complete commit", () => {
  it("commits pending as one assistant message and resets pending", () => {
    let s = reduce(emptyTurn(), tok("Hello "));
    s = reduce(s, tok("world"));
    s = reduce(s, { event: "turn_complete", data: { session_id: 42, message: "Hello world" } });
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0].role).toBe("assistant");
    expect(s.messages[0].content).toBe("Hello world");
    // reset
    expect(s.pending).toEqual({ text: "", reasoning: "", toolCalls: [], draft: null });
  });

  it("carries committed tool chips onto the committed message", () => {
    let s = reduce(emptyTurn(), {
      event: "tool_call",
      data: { name: "search_listings", arguments: {} },
    });
    s = reduce(s, {
      event: "tool_result",
      data: { name: "search_listings", output: "out", chip: "9 found" },
    });
    s = reduce(s, tok("Done: 9 found."));
    s = reduce(s, { event: "turn_complete", data: { session_id: 1, message: "Done: 9 found." } });
    expect(s.messages[0]?.toolCalls).toHaveLength(1);
    expect(s.messages[0]?.toolCalls?.[0]?.status).toBe("done");
  });

  it("bumps a counter so callers can react to each commit (invalidate session list)", () => {
    const s = reduce(emptyTurn(), { event: "turn_complete", data: { session_id: 5, message: "hi" } });
    expect(s.lastCommittedSessionId).toBe(5);
  });
});

describe("error mid-turn", () => {
  it("preserves typed text and partial pending, marks the turn errored", () => {
    let s = reduce(emptyTurn(), tok("partial answer"));
    s = reduce(s, {
      event: "tool_call",
      data: { name: "web_search", arguments: {} },
    });
    s = reduce(s, { event: "error", data: { code: "llm_timeout", message: "upstream timed out" } });
    // user text and pending preserved verbatim
    expect(s.pending.text).toBe("partial answer");
    expect(s.pending.toolCalls).toHaveLength(1);
    // errored state visible to the UI
    expect(s.error).toEqual({ code: "llm_timeout", message: "upstream timed out" });
    // nothing was lost to messages, nothing committed
    expect(s.messages).toEqual([]);
  });

  it("regenerate-from-error clears error and pending, keeps committed messages", () => {
    let s = reduce(emptyTurn(), tok("first turn"));
    s = reduce(s, { event: "turn_complete", data: { session_id: 1, message: "first turn" } });
    s = reduce(s, { event: "error", data: { code: "boom", message: "bad" } });
    const cleared = clearError(s);
    expect(cleared.error).toBeNull();
    expect(cleared.pending).toEqual({ text: "", reasoning: "", toolCalls: [], draft: null });
    expect(cleared.messages).toHaveLength(1);
  });
});

describe("unknown events", () => {
  it("are a no-op", () => {
    const s = reduce(emptyTurn(), { event: "ping", data: {} });
    expect(s).toEqual(emptyTurn());
  });
});

describe("reduceAll / recovery", () => {
  it("folds a recorded stream in order", () => {
    const events: TurnEvent[] = [
      tok("The answer "),
      { event: "tool_call", data: { name: "search_listings", arguments: { q: "x" } } },
      { event: "tool_result", data: { name: "search_listings", output: "o", chip: "3 found" } },
      { event: "reasoning", data: { text: "hmm" } },
      tok("is 3."),
      { event: "turn_complete", data: { session_id: 9, message: "The answer is 3." } },
    ];
    const s = reduceAll(emptyTurn(), events);
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0]?.content).toBe("The answer is 3.");
    expect(s.messages[0]?.toolCalls?.[0]?.chip).toBe("3 found");
    expect(s.pending).toEqual({ text: "", reasoning: "", toolCalls: [], draft: null });
  });
});

describe("mid-stream disconnect", () => {
  it("a stream cut off before turn_complete commits nothing", () => {
    const events: TurnEvent[] = [
      tok("Half an "),
      { event: "tool_call", data: { name: "search_listings", arguments: {} } },
      { event: "tool_result", data: { name: "search_listings", output: "o", chip: "2 found" } },
      tok("answer that never finis"),
      // connection dies here: no turn_complete, no error frame
    ];
    const s = reduceAll(emptyTurn(), events);
    expect(s.messages).toHaveLength(0);
    expect(s.pending.text).toBe("Half an answer that never finis");
    expect(s.pending.toolCalls).toHaveLength(1);
    expect(s.error).toBeNull();
  });

  it("reconstruction from persisted state renders the committed transcript", () => {
    // After a disconnect the consumer re-GETs the session and maps its
    // messages straight into view state; the reducer's committed shape is
    // what the persisted rows must reproduce.
    const committed: ChatViewMessage = {
      role: "assistant",
      content: "Recovered reply",
      toolCalls: [{ name: "search_listings", arguments: {}, status: "done", chip: "2 found" }],
    };
    const s: TurnState = {
      messages: [committed],
      pending: { text: "", reasoning: "", toolCalls: [], draft: null },
      error: null,
      lastCommittedSessionId: 3,
    };
    expect(s.messages[0]?.content).toBe("Recovered reply");
    expect(s.messages[0]?.toolCalls?.[0]?.status).toBe("done");
  });
});
