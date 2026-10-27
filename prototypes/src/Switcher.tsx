import { useEffect } from "react";
import { useTheme } from "./theme";

const VARIANTS: Record<string, string> = {
  A: "Verdict-first column",
  B: "Photo grid",
  C: "Dense ledger",
};
const KEYS = ["A", "B", "C"];

// Floating bottom-center pill: cycles variants, flips theme. Deliberately loud
// so it reads as prototype scaffolding, not page design.
export default function Switcher() {
  const theme = useTheme();
  const current =
    new URLSearchParams(window.location.search).get("variant") ?? "A";

  const go = (key: string) => {
    const p = new URLSearchParams(window.location.search);
    p.set("variant", key);
    window.history.replaceState(null, "", `?${p.toString()}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  const flipTheme = () => {
    const p = new URLSearchParams(window.location.search);
    p.set("theme", theme === "dark" ? "light" : "dark");
    window.history.replaceState(null, "", `?${p.toString()}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (
        t.tagName === "INPUT" ||
        t.tagName === "TEXTAREA" ||
        t.isContentEditable
      )
        return;
      const i = KEYS.indexOf(
        new URLSearchParams(window.location.search).get("variant") ?? "A"
      );
      if (e.key === "ArrowRight") go(KEYS[(i + 1) % KEYS.length]);
      if (e.key === "ArrowLeft")
        go(KEYS[(i - 1 + KEYS.length) % KEYS.length]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
      <button onClick={() => go("A")}>A</button>
      <button onClick={() => go("B")}>B</button>
      <button onClick={() => go("C")}>C</button>
      <span>
        {current} — {VARIANTS[current]}
      </span>
      <button onClick={flipTheme}>
        {theme === "dark" ? "☀ light" : "☾ dark"}
      </button>
    </div>
  );
}
