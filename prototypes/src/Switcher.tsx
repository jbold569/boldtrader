// Floating bottom-center pill: switches tile/condensed, flips theme.
// Deliberately loud so it reads as prototype scaffolding, not page design.

import { patchUrl } from "./filters";
import { useTheme } from "./theme";

export default function Switcher() {
  const theme = useTheme();
  const view =
    new URLSearchParams(window.location.search).get("view") === "condensed"
      ? "condensed"
      : "tile";

  return (
    <div
      style={{
        position: "fixed",
        bottom: 14,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 50,
        display: "flex",
        gap: 10,
        alignItems: "center",
        background: "var(--fg)",
        color: "var(--bg)",
        borderRadius: 99,
        padding: "6px 8px",
        boxShadow: "0 2px 10px rgba(0,0,0,.35)",
        fontSize: 13,
      }}
    >
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
      <button onClick={() => patchUrl({ theme: theme === "dark" ? "light" : "dark" })}>
        {theme === "dark" ? "☀ light" : "☾ dark"}
      </button>
    </div>
  );
}
