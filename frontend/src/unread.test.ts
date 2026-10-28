// Unread tracking tests (ticket #49). The subtle bit: the server stores
// second-precision ISO stamps; JS produces millisecond stamps. Both sides are
// truncated to seconds before comparing, or equal timestamps compare "unread".

import { describe, it, expect } from "vitest";
import { isUnread, markViewed, unreadCount, UNREAD_KEY, type ViewedMap } from "./unread";

// localStorage shim for the node test environment.
const store: Record<string, string> = {};
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => store[k] ?? null,
  setItem: (k: string, v: string) => {
    store[k] = v;
  },
};

describe("isUnread", () => {
  it("is unread when never viewed", () => {
    expect(isUnread({ id: 1, updated_at: "2026-10-28T10:00:00Z" }, {})).toBe(true);
  });

  it("is read when viewed at the same second", () => {
    const viewed: ViewedMap = { "1": "2026-10-28T10:00:00" };
    expect(isUnread({ id: 1, updated_at: "2026-10-28T10:00:00Z" }, viewed)).toBe(false);
  });

  it("is unread when updated after the viewed timestamp", () => {
    const viewed: ViewedMap = { "1": "2026-10-28T10:00:00" };
    expect(isUnread({ id: 1, updated_at: "2026-10-28T10:00:01Z" }, viewed)).toBe(true);
  });
});

describe("markViewed", () => {
  it("truncates to seconds and persists under the key", () => {
    const next = markViewed({}, 7, "2026-10-28T10:30:45.123Z");
    expect(next["7"]).toBe("2026-10-28T10:30:45");
    expect(JSON.parse(store[UNREAD_KEY])["7"]).toBe("2026-10-28T10:30:45");
  });
});

describe("unreadCount", () => {
  it("counts only sessions newer than their viewed stamp", () => {
    const viewed: ViewedMap = {
      "1": "2026-10-28T12:00:00",
      "2": "2026-10-28T09:00:00",
    };
    const sessions = [
      { id: 1, updated_at: "2026-10-28T11:00:00Z" },
      { id: 2, updated_at: "2026-10-28T11:30:00Z" },
      { id: 3, updated_at: "2026-10-28T11:45:00Z" },
    ];
    expect(unreadCount(sessions, viewed)).toBe(2);
  });
});
