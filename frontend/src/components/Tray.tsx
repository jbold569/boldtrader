// App tray — settled Variant B (#32): a bottom sheet that pulls up from a
// 28px grip peek at the bottom edge. Drag up or tap the grip to open; drag
// down, tap the scrim, or press Escape to close. Payload (user verdict,
// #22): ＋ New Chat → Bargains + Search pair → Chat Sessions → theme
// toggle. No menu icon on the grip, no "Chat" nav item — the sessions
// list covers it. Ported from prototypes/src/trays.tsx TrayB.
//
// NOTE: the prototype's 💰 badge (unread deal count) is omitted — API v1
// has no unread-deal concept on the wire and we never fake data.

import {
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listChatSessions } from "../api/client";
import { unreadCount, type ViewedMap } from "../unread";
import "./tray.css";

interface Props {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  viewed: ViewedMap;
  children: ReactNode;
}

const PEEK_H = 28; // must equal rendered grip height; larger exposes New Chat when hidden

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

// Short relative time for the session rows ("now", "2m", "1h", "yest").
export function when(iso: string): string {
  if (!iso) return "";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  if (hrs < 48) return "yest";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function TrayBody({
  theme,
  onToggleTheme,
  viewed,
  onPick,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  viewed: ViewedMap;
  onPick: () => void;
}) {
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["chatSessions"],
    queryFn: () => listChatSessions(1),
  });
  const sessions = data?.items ?? [];

  return (
    <div className="tray-body">
      <button
        className="tray-newchat"
        onClick={() => {
          onPick();
          navigate("/");
        }}
      >
        ＋ New Chat
      </button>
      <div className="tray-pair">
        <Link className="tray-half" to="/bargains" onClick={onPick}>
          💰 Bargains
        </Link>
        <Link className="tray-half" to="/search" onClick={onPick}>
          🔍 Search
        </Link>
      </div>
      <h2>Chat Sessions</h2>
      <ul className="tray-sessions" aria-label="Chat Sessions">
        {sessions.map((s) => (
          <li key={s.id}>
            <Link to={`/chat/${s.id}`} onClick={onPick}>
              {unreadCount([s], viewed) > 0 && (
                <span className="dot" aria-label="unread" />
              )}
              {s.title || "Untitled"}
            </Link>
            <span className="muted tray-when">{when(s.updated_at)}</span>
          </li>
        ))}
        <li>
          <Link className="tray-viewall" to="/chat/sessions" onClick={onPick}>
            View all →
          </Link>
        </li>
      </ul>
      <div className="tray-foot">
        <button
          className="tray-theme"
          onClick={onToggleTheme}
          aria-label={`switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? "☀ Light" : "🌙 Dark"}
        </button>
      </div>
    </div>
  );
}

export default function Tray({ theme, onToggleTheme, viewed, children }: Props) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y0: number; p0: number; moved: number } | null>(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    const k = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  function start(e: PointerEvent) {
    if ((e.target as HTMLElement).closest("button,a,input")) return;
    try {
      (e.target as Element).setPointerCapture?.(e.pointerId);
    } catch {
      // capture can fail on synthetic events; dragging degrades gracefully
    }
    const h = panel.current?.offsetHeight ?? 400;
    drag.current = { y0: e.clientY, p0: open ? 0 : h - PEEK_H, moved: 0 };
  }
  function move(e: PointerEvent) {
    if (!drag.current || !panel.current) return;
    const h = panel.current.offsetHeight;
    const dy = e.clientY - drag.current.y0;
    drag.current.moved = Math.abs(dy);
    if (drag.current.moved > 8) panel.current.classList.add("dragging");
    panel.current.style.transform = `translateY(${clamp(
      drag.current.p0 + dy,
      0,
      h - PEEK_H,
    )}px)`;
  }
  function end(e: PointerEvent) {
    if (!drag.current) return;
    const dy = e.clientY - drag.current.y0;
    const wasDrag = drag.current.moved > 24;
    drag.current = null;
    panel.current?.classList.remove("dragging");
    if (panel.current) panel.current.style.transform = "";
    suppressClick.current = wasDrag;
    if (dy < -48) setOpen(true);
    else if (dy > 48) setOpen(false);
  }
  function gripClick() {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    setOpen((o) => !o);
  }

  return (
    <div className="shell-b">
      <div className="shell-b-body">{children}</div>
      {open && <div className="scrim show" onClick={() => setOpen(false)} />}
      <div
        ref={panel}
        className={"sheet" + (open ? " open" : "")}
        role="dialog"
        aria-modal={open}
        aria-label="Navigation"
      >
        <div
          className="sheet-grip"
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={end}
          onClick={gripClick}
          aria-label="Pull up navigation tray"
        >
          <span className="grip-pill" />
        </div>
        <TrayBody theme={theme} onToggleTheme={onToggleTheme} viewed={viewed} onPick={() => setOpen(false)} />
      </div>
    </div>
  );
}
