// Floating bottom-center pill: switches nav tray variant (A/B/C), page
// (results / search forms / chat + each page's variant A/B/C), and the
// reasoning channel (chat only). Theme lives as a small button fixed at
// top-right, clear of the pill and the chat input bar. Deliberately loud
// so it reads as prototype scaffolding, not page design.

import { patchUrl } from "./filters";
import { useTheme } from "./theme";

const NAVS = [
  { k: "a", label: "A Drawer" },
  { k: "b", label: "B Sheet" },
  { k: "c", label: "C Visible" },
];

const FORMS = [
  { k: "a", label: "A Classic" },
  { k: "b", label: "B Chips" },
  { k: "c", label: "C Wizard" },
];

const CHATS = [
  { k: "a", label: "A Waterfall" },
  { k: "b", label: "B Work Log" },
  { k: "c", label: "C Inspector" },
];

export default function Switcher() {
  const theme = useTheme();
  const q = new URLSearchParams(window.location.search);
  const view = q.get("view") === "condensed" ? "condensed" : "tile";
  const nav = (q.get("nav") ?? "a").toLowerCase();
  const idx = Math.max(0, NAVS.findIndex((n) => n.k === nav));
  const page = q.get("page") ?? "results";
  const isSearch = page === "search";
  const isChat = page === "chat";
  const form = (q.get("form") ?? "a").toLowerCase();
  const fidx = Math.max(0, FORMS.findIndex((f) => f.k === form));
  const chat = (q.get("chat") ?? "a").toLowerCase();
  const cidx = Math.max(0, CHATS.findIndex((c) => c.k === chat));
  const showReason = q.get("reason") !== "hide";

  const cycle = (key: string, list: { k: string }[], cur: number, dir: 1 | -1) =>
    patchUrl({ [key]: list[(cur + dir + list.length) % list.length].k });

  return (
    <>
      <button
        className="sw-theme"
        aria-label="Toggle theme"
        onClick={() => patchUrl({ theme: theme === "dark" ? "light" : "dark" })}
      >
        {theme === "dark" ? "☀" : "🌙"}
      </button>
      <div
        style={{
          position: "fixed",
          bottom: nav === "a" ? 14 : 72,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 300,
          display: "flex",
          gap: 8,
          alignItems: "center",
          background: "var(--fg)",
          color: "var(--bg)",
          borderRadius: 99,
          padding: "6px 8px",
          boxShadow: "0 2px 10px rgba(0,0,0,.35)",
          fontSize: 13,
          maxWidth: "94vw",
        }}
      >
        <button
          aria-label="Previous nav variant"
          onClick={() => cycle("nav", NAVS, idx, -1)}
        >
          ◀
        </button>
        <span style={{ fontWeight: 700 }}>🧭 {NAVS[idx].label}</span>
        <button
          aria-label="Next nav variant"
          onClick={() => cycle("nav", NAVS, idx, 1)}
        >
          ▶
        </button>
        <span style={{ opacity: 0.4 }}>|</span>
        {isChat ? (
          <>
            <button
              aria-label="Previous chat variant"
              onClick={() => cycle("chat", CHATS, cidx, -1)}
            >
              ◀
            </button>
            <span style={{ fontWeight: 700 }}>💬 {CHATS[cidx].label}</span>
            <button
              aria-label="Next chat variant"
              onClick={() => cycle("chat", CHATS, cidx, 1)}
            >
              ▶
            </button>
            <button
              onClick={() => patchUrl({ reason: showReason ? "hide" : "show" })}
            >
              🧠 {showReason ? "shown" : "hidden"}
            </button>
            <button onClick={() => patchUrl({ page: "results", chat: null })}>
              ≣ Results
            </button>
            <button
              onClick={() => patchUrl({ page: "search", chat: null, form: "a" })}
            >
              🔍 Forms
            </button>
          </>
        ) : isSearch ? (
          <>
            <button
              aria-label="Previous form variant"
              onClick={() => cycle("form", FORMS, fidx, -1)}
            >
              ◀
            </button>
            <span style={{ fontWeight: 700 }}>🔍 {FORMS[fidx].label}</span>
            <button
              aria-label="Next form variant"
              onClick={() => cycle("form", FORMS, fidx, 1)}
            >
              ▶
            </button>
            <button onClick={() => patchUrl({ page: "results", form: null })}>
              ≣ Results
            </button>
            <button onClick={() => patchUrl({ page: "chat", chat: "a" })}>
              💬 Chat
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => patchUrl({ view: "tile" })}
              aria-pressed={view === "tile"}
            >
              ▦ Tile
            </button>
            <button
              onClick={() => patchUrl({ view: "condensed" })}
              aria-pressed={view === "condensed"}
            >
              ☰ Condensed
            </button>
            <button onClick={() => patchUrl({ page: "search", form: "a" })}>
              🔍 Search forms
            </button>
            <button onClick={() => patchUrl({ page: "chat", chat: "a" })}>
              💬 Chat
            </button>
          </>
        )}
      </div>
    </>
  );
}
