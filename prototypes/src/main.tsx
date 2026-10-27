// Throwaway prototype for wayfinder #34 — Bargain Search results look-and-feel.
// Two views of one query: `?view=tile` (verdict-first cards) and
// `?view=condensed` (dense ledger), sharing one FilterBar and a light/dark
// token ramp (`?theme=light|dark`). Fake data inline; no backend calls.

import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ThemeContext, type Theme } from "./theme";
import { LISTINGS, SEARCH } from "./data";
import { parseFilters, applyFilters } from "./filters";
import FilterBar from "./FilterBar";
import TileView from "./TileView";
import CondensedView from "./CondensedView";
import Switcher from "./Switcher";
import "./base.css";

function useQuery() {
  const [params, setParams] = useState(
    () => new URLSearchParams(window.location.search)
  );
  useEffect(() => {
    const sync = () => setParams(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  return params;
}

function App() {
  const q = useQuery();
  const view = q.get("view") === "condensed" ? "condensed" : "tile";
  const theme: Theme = q.get("theme") === "dark" ? "dark" : "light";
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const results = applyFilters(LISTINGS, parseFilters(q));

  return (
    <ThemeContext.Provider value={theme}>
      <div className="page">
        <div className="banner">
          Sifting {SEARCH.live.sifted}/{SEARCH.live.total} ·{" "}
          <strong>{SEARCH.live.new_deals} new deals</strong> since you last looked
        </div>
        <FilterBar count={results.length} />
        {view === "tile" ? (
          <TileView listings={results} />
        ) : (
          <CondensedView listings={results} />
        )}
      </div>
      <Switcher />
    </ThemeContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
