// Unread Chat Session tracking (ticket #49). Pure module: state is a
// {sessionId -> last-viewed ISO timestamp} map persisted under one
// localStorage key (same pattern as theme.ts). A session is unread when its
// updated_at is newer than the moment the user last viewed it. Chat turns are
// not published on the global SSE stream, so "viewed" is marked by the
// consumer on turn_complete and on opening a session.

export type ViewedMap = Record<string, string>;

export interface SessionLike {
  id: number | string;
  updated_at: string;
}

export const UNREAD_KEY = "boldtrader-chat-viewed";

export function loadViewed(): ViewedMap {
  try {
    const raw = localStorage.getItem(UNREAD_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as ViewedMap) : {};
  } catch {
    return {};
  }
}

export function saveViewed(map: ViewedMap): void {
  localStorage.setItem(UNREAD_KEY, JSON.stringify(map));
}

// Server timestamps are second-precision ISO; stored/viewed values are
// truncated to the same precision so the string comparison is exact
// (a `...32.123Z` seen-value would sort BEFORE an equal `...32Z` update).
function sec(iso: string): string {
  return (iso || "").slice(0, 19);
}

export function markViewed(
  map: ViewedMap,
  sessionId: number | string,
  at: string = new Date().toISOString(),
): ViewedMap {
  const next = { ...map, [String(sessionId)]: sec(at) };
  saveViewed(next);
  return next;
}

export function isUnread(session: SessionLike, viewed: ViewedMap): boolean {
  const seen = viewed[String(session.id)];
  if (!seen) return true;
  return sec(session.updated_at) > seen;
}

export function unreadCount(sessions: SessionLike[], viewed: ViewedMap): number {
  return sessions.filter((s) => isUnread(s, viewed)).length;
}
