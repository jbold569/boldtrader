// Floating bottom-center pill: switches nav tray variant (A/B/C), results
// view (tile/condensed), and theme. Deliberately loud so it reads as
// prototype scaffolding, not page design.

import { patchUrl } from "./filters";
import { useTheme } from "./theme";

const NAVS = [
  { k: "a", label: "A Drawer" },
  { k: "b", label: "B Sheet" },
  { k: "c", label: "C Visible" },
];

export default function Switcher() {
  const theme = useTheme();
  const q = new URLSearchParams(window.location.search);
  const view = q.get("view") === "condensed" ? "condensed" : "tile";
  const nav = (q.get("nav") ?? "a").toLowerCase();
  const idx = Math.max(0, NAVS.findIndex((n) => n.k === nav));

  return (
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
        onClick={() =>
          patchUrl({ nav: NAVS[(idx - 1 + NAVS.length) % NAVS.length].k })
        }
      >
        ◀
      </button>
      <span style={{ fontWeight: 700 }}>{NAVS[idx].label}</span>
      <button
        aria-label="Next nav variant"
        onClick={() => patchUrl({ nav: NAVS[(idx + 1) % NAVS.length].k })}
      >
        ▶
      </button>
      <span style={{ opacity: 0.4 }}>|</span>
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
      <span style={{ opacity: 0.4 }}>|</span>
      <button onClick={() => patchUrl({ theme: theme === "dark" ? "light" : "dark" })}>
        {theme === "dark" ? "☀ light" : "☾ dark"}
      </button>
    </div>
  );
}
