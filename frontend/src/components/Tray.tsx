// App tray (ticket #49, #32 Variant C): persistent sidebar ≥768px and a
// fixed bottom tab bar <768px, both carrying the same payload:
// ＋ New Chat → destinations → Chat Sessions list → theme toggle.
// The sidebar never collapses: the payload is fully visible at every width.

import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listChatSessions } from "../api/client";
import { unreadCount, type ViewedMap } from "../unread";
import "./tray.css";

interface Props {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  viewed: ViewedMap;
}

export default function Tray({ theme, onToggleTheme, viewed }: Props) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { data } = useQuery({
    queryKey: ["chatSessions"],
    queryFn: () => listChatSessions(1),
  });
  const sessions = data?.items ?? [];
  const unread = unreadCount(sessions, viewed);

  return (
    <>
      <aside className="sidebar">
        <div className="tray-brand">BoldTrader</div>
        <button className="tray-newchat" onClick={() => navigate("/")}>
          ＋ New Chat
        </button>
        <div className="tray-pair">
          <Link className="tray-half" to="/bargains">
            💰 Bargains
          </Link>
          <Link className="tray-half" to="/search">
            🔍 Search
          </Link>
        </div>
        <nav className="tray-sessions" aria-label="Chat Sessions">
          {sessions.map((s) => (
            <Link key={s.id} to={`/chat/${s.id}`}>
              {unreadCount([s], viewed) > 0 && <span className="dot" aria-label="unread" />}
              <span className="tray-title">{s.title || "Untitled"}</span>
            </Link>
          ))}
          {sessions.length > 0 && (
            <Link className="tray-viewall" to="/chat/sessions">
              View all →
            </Link>
          )}
        </nav>
        <div className="tray-foot">
          <button
            className="tray-theme"
            onClick={onToggleTheme}
            aria-label={`switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </aside>
      <nav className="tabbar" aria-label="Primary">
        <Link className="tab" to="/" onClick={() => navigate("/")}>
          💬 Chat
          {unread > 0 && <span className="tab-badge">{unread}</span>}
        </Link>
        <Link className={`tab ${pathname.startsWith("/bargains") ? "active" : ""}`} to="/bargains">
          💰 Bargains
        </Link>
        <Link className={`tab ${pathname.startsWith("/search") ? "active" : ""}`} to="/search">
          🔍 Search
        </Link>
      </nav>
    </>
  );
}
