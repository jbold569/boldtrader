// Side-tray navigation prototype — wayfinder #32.
// Three structural takes on app navigation, switchable with ?nav=a|b|c:
//   A  off-canvas left drawer (today's pattern): hamburger trigger, scrim,
//      swipe right from the left edge to open
//   B  bottom sheet: grip bar peeking at the bottom edge, swipe/drag up to
//      open, drag down or tap scrim to close
//   C  no hidden navigation: persistent sidebar on desktop (>=768px),
//      fixed bottom tab bar on phone
// Throwaway. Fake data inline; no backend calls.
//
// Theme toggle lives as a single small fixed button top-right (.sw-theme in
// chat.css), rendered by Switcher — NOT inside the trays.

import {
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from "react";
import "./trays.css";

const NAV = [
  { key: "chat", icon: "💬", label: "Chat", badge: 1 },
  { key: "bargains", icon: "💰", label: "Bargains", badge: 2 },
  { key: "search", icon: "🔍", label: "Search", badge: 0 },
];

const SESSIONS = [
  { id: "c1", title: "Best Xeon E5 bundles under $200", when: "2m", unread: true },
  { id: "c2", title: "Is this Dell OptiPlex a deal?", when: "1h", unread: true },
  { id: "c3", title: "DDR4 3200 price history", when: "3h", unread: false },
  { id: "c4", title: "Authored description — Lenovo M920q", when: "yest", unread: false },
  { id: "c5", title: "Flip values for RTX 3060 bundles", when: "yest", unread: false },
];

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

// The payload every hidden-nav variant carries: primary action, the three
// top-level destinations, recent Chat Sessions.
function TrayBody({ onPick }: { onPick: () => void }) {
  return (
    <div className="tray-body">
      <button className="tray-newchat" onClick={onPick}>
        ＋ New Chat
      </button>
      <nav className="tray-nav">
        {NAV.map((it) => (
          <a
            key={it.key}
            href="#"
            className="tray-link"
            onClick={(e) => {
              e.preventDefault();
              onPick();
            }}
          >
            <span>{it.icon}</span>
            <span>{it.label}</span>
            {it.badge > 0 && <span className="chip ok tray-badge">{it.badge}</span>}
          </a>
        ))}
      </nav>
      <h2>Chat Sessions</h2>
      <ul className="tray-sessions">
        {SESSIONS.map((s) => (
          <li key={s.id}>
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                onPick();
              }}
            >
              {s.unread && <span className="dot" />}
              {s.title}
            </a>
            <span className="muted tray-when">{s.when}</span>
          </li>
        ))}
        <li>
          <a
            className="tray-viewall"
            href="#"
            onClick={(e) => {
              e.preventDefault();
              onPick();
            }}
          >
            View all →
          </a>
        </li>
      </ul>
    </div>
  );
}

// ---- A: off-canvas left drawer ----
const DRAWER_W = 300;

export function TrayA({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x0: number; p0: number } | null>(null);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
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
    } catch {}
    panel.current?.classList.add("dragging");
    drag.current = { x0: e.clientX, p0: open ? 0 : -DRAWER_W };
  }
  function move(e: PointerEvent) {
    if (!drag.current || !panel.current) return;
    const dx = e.clientX - drag.current.x0;
    panel.current.style.transform = `translateX(${clamp(
      drag.current.p0 + dx,
      -DRAWER_W,
      0
    )}px)`;
  }
  function end(e: PointerEvent) {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x0;
    drag.current = null;
    panel.current?.classList.remove("dragging");
    if (panel.current) panel.current.style.transform = "";
    if (dx > 48) setOpen(true);
    else if (dx < -48) setOpen(false);
  }

  return (
    <div className="shell-a">
      <header className="topbar">
        <button
          className="menu-toggle"
          aria-label="Open menu"
          aria-expanded={open}
          aria-controls="nav-tray"
          onClick={() => setOpen(!open)}
        >
          ☰
        </button>
        <a className="brand" href="#">
          BoldTrader
        </a>
        <span className="topbar-spacer" />
      </header>
      <div className="shell-a-body">{children}</div>
      {open && <div className="scrim show" onClick={() => setOpen(false)} />}
      <div
        id="nav-tray"
        ref={panel}
        className={"drawer" + (open ? " open" : "")}
        role="dialog"
        aria-modal={open}
        aria-label="Navigation"
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
      >
        <TrayBody onPick={() => setOpen(false)} />
      </div>
      {!open && (
        <div
          className="edge-strip"
          aria-hidden="true"
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={end}
        />
      )}
    </div>
  );
}

// ---- B: bottom sheet ----
const PEEK_H = 46;

export function TrayB({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y0: number; p0: number; moved: number } | null>(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
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
    } catch {}
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
      h - PEEK_H
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
          aria-label="Open menu"
        >
          <span className="grip-pill" />
          <span className="grip-label">☰ Menu</span>
        </div>
        <TrayBody onPick={() => setOpen(false)} />
      </div>
    </div>
  );
}

// ---- C: no hidden nav ----
export function TrayC({ children }: { children: ReactNode }) {
  return (
    <div className="shell-c">
      <aside className="sidebar">
        <a className="brand" href="#">
          BoldTrader
        </a>
        <TrayBody onPick={() => {}} />
      </aside>
      <main className="main-c">{children}</main>
      <nav className="tabbar" aria-label="Main">
        {NAV.map((t) => (
          <a
            key={t.key}
            className="tab"
            href="#"
            onClick={(e) => e.preventDefault()}
          >
            <span>{t.icon}</span>
            <span className="tab-label">{t.label}</span>
            {t.badge > 0 && <span className="chip ok tab-badge">{t.badge}</span>}
          </a>
        ))}
        <button className="tab">
          <span>＋</span>
          <span className="tab-label">New Chat</span>
        </button>
      </nav>
    </div>
  );
}
