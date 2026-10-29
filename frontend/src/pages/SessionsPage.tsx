// Chat Sessions list page (ticket #49; look from prototypes/src/sessions.tsx):
// fuzzy search over session titles, flush list rows with unread dot and
// when-time. Reached from the tray's "View all →".

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { deleteChatSession, listChatSessions } from "../api/client";
import { isUnread, loadViewed } from "../unread";
import { when } from "../components/Tray";
import "./sessions.css";

// subsequence fuzzy match: every query char appears in order in the target.
// bonus points for a contiguous word hit. Returns -1 for no match.
export function fuzzy(q: string, text: string): number {
  if (!q) return 0;
  const t = text.toLowerCase();
  const s = q.toLowerCase().trim();
  let score = 0;
  let ti = 0;
  for (const ch of s) {
    if (ch === " ") continue;
    const at = t.indexOf(ch, ti);
    if (at === -1) return -1;
    score += at === ti ? 2 : 1;
    ti = at + 1;
  }
  if (t.includes(s)) score += 10;
  return score;
}

export default function SessionsPage() {
  const [q, setQ] = useState("");
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["chatSessions"],
    queryFn: () => listChatSessions(1),
  });
  const sessions = useMemo(() => data?.items ?? [], [data]);

  const results = useMemo(() => {
    if (!q.trim()) return sessions;
    return sessions
      .map((s) => ({ s, sc: fuzzy(q, s.title || "Untitled") }))
      .filter((r) => r.sc >= 0)
      .sort((a, b) => b.sc - a.sc)
      .map((r) => r.s);
  }, [q, sessions]);

  const onDelete = async (id: number, title: string) => {
    if (!window.confirm(`Delete Chat Session "${title}"?`)) return;
    await deleteChatSession(id);
    queryClient.invalidateQueries({ queryKey: ["chatSessions"] });
  };

  if (isLoading) return <p className="sp-empty">Loading…</p>;
  if (error) return <p className="sp-empty sp-err">Failed to load sessions.</p>;

  return (
    <div className="sp">
      <div className="sp-search">
        <input
          autoFocus
          type="search"
          placeholder="Search past sessions…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search past chat sessions"
        />
        <span className="sp-count muted" aria-live="polite">
          {results.length} of {sessions.length}
        </span>
      </div>
      {results.length === 0 ? (
        <p className="sp-empty muted">No session matches “{q}”.</p>
      ) : (
        <ul className="sp-list">
          {results.map((s) => (
            <li key={s.id} className="sp-item">
              <Link to={`/chat/${s.id}`}>
                {isUnread(s, loadViewed()) && <span className="dot" />}
                <span className="muted sp-when">{when(s.updated_at)}</span>
              </Link>
              <button
                type="button"
                className="sp-del"
                onClick={() => void onDelete(s.id, s.title || "Untitled")}
                aria-label={`delete session ${s.title || "Untitled"}`}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
