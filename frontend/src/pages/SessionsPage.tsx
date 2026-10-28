// Chat Sessions list page: full list with delete. Reached from the tray's
// "View all →". Ticket #49.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { deleteChatSession, listChatSessions } from "../api/client";

export default function SessionsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["chatSessions"],
    queryFn: () => listChatSessions(1),
  });

  const onDelete = async (id: number, title: string) => {
    if (!window.confirm(`Delete Chat Session "${title}"?`)) return;
    await deleteChatSession(id);
    queryClient.invalidateQueries({ queryKey: ["chatSessions"] });
  };

  if (isLoading) return <p style={{ padding: "var(--space-4)" }}>Loading…</p>;
  if (error)
    return <p style={{ padding: "var(--space-4)", color: "var(--bad)" }}>Failed to load sessions.</p>;

  return (
    <section style={{ padding: "var(--space-4)" }}>
      <h1 style={{ fontSize: "var(--text-xl)", color: "var(--fg)", marginTop: 0 }}>
        Chat Sessions
      </h1>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "var(--space-2)" }}>
        {(data?.items ?? []).map((s) => (
          <li
            key={s.id}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "var(--space-3)",
              padding: "var(--space-2) var(--space-3)",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <Link to={`/chat/${s.id}`} style={{ color: "var(--fg)" }}>
              {s.title || "Untitled"}
            </Link>
            <button
              className="ct-regen"
              onClick={() => void onDelete(s.id, s.title || "Untitled")}
              aria-label={`delete session ${s.title || "Untitled"}`}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
