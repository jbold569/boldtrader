// Prototype chrome: a small fixed pill to hop between the prototype pages.
// All variant roulette is over — decisions are locked: tray B pull-up (#32 rev),
// tile/condensed (#34), search form A classic (#33), chat B work log (#21),
// reasoning suppressed (#21). Theme toggle lives in the tray footer (#32 rev).

import { patchUrl } from "./filters";

export default function Switcher() {
  const q = new URLSearchParams(window.location.search);
  const view = q.get("view") === "condensed" ? "condensed" : "tile";
  return (
    <div
      style={{
        position: "fixed",
        bottom: 44,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 300,
        display: "flex",
        gap: 8,
        alignItems: "center",
        background: "var(--fg)",
        color: "var(--bg)",
        borderRadius: 99,
        padding: "6px 10px",
        boxShadow: "0 2px 10px rgba(0,0,0,.35)",
        fontSize: 13,
        maxWidth: "94vw",
      }}
    >
      <button onClick={() => patchUrl({ view: "tile" })} aria-pressed={view === "tile"}>
        ▦ Tile
      </button>
      <button
        onClick={() => patchUrl({ view: "condensed" })}
        aria-pressed={view === "condensed"}
      >
        ☰ Condensed
      </button>
      <button onClick={() => patchUrl({ page: "search", form: "a" })}>
        🔍 Search
      </button>
      <button onClick={() => patchUrl({ page: "chat", chat: "b" })}>
        💬 Chat
      </button>
      <button onClick={() => patchUrl({ page: "live" })}>📡 Live</button>
      <button onClick={() => patchUrl({ page: "sessions" })}>🗂 Sessions</button>
    </div>
  );
}
