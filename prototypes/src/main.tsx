// Shared throwaway prototype app.
//   #34 results look-and-feel: `?view=tile|condensed`
//   #32 side-tray navigation:  `?nav=a|b|c`
//   #33 search forms:          `?page=search&form=a|b|c`
//   #21 chat page UX:          `?page=chat&chat=a|b|c&reason=show|hide`
//   #22 live interactions:     `?page=live` (mock server; `req=immediate|submit&debounce=ms`)
// Light/dark everywhere via `?theme=light|dark`. Fake data inline; no backend.

import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ThemeContext, type Theme } from "./theme";
import { LISTINGS, SEARCH } from "./data";
import { parseFilters, applyFilters } from "./filters";
import FilterBar from "./FilterBar";
import TileView from "./TileView";
import CondensedView from "./CondensedView";
import Switcher from "./Switcher";
import { TrayA, TrayB, TrayC } from "./trays";
import SearchPage from "./search";
import ChatPage from "./chat";
import LivePage from "./live";
import SessionsPage from "./sessions";
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

// The page content under test: a results page stands in for "whatever page you
// are on", since the tray is global chrome seen from every route.
function ResultsPage() {
  const q = useQuery();
  const view = q.get("view") === "condensed" ? "condensed" : "tile";
  const results = applyFilters(LISTINGS, parseFilters(q));
  return (
    <>
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
    </>
  );
}

function App() {
  const q = useQuery();
  const theme: Theme = q.get("theme") === "dark" ? "dark" : "light";
  const nav = (q.get("nav") ?? "b").toLowerCase();
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const isSearch = q.get("page") === "search";
  const isChat = q.get("page") === "chat";
  const isLive = q.get("page") === "live";
  const isSessions = q.get("page") === "sessions";
  const page = isChat ? (
    <ChatPage
      variant={(q.get("chat") ?? "a").toLowerCase() as "a" | "b" | "c"}
    />
  ) : isLive ? (
    <LivePage />
  ) : isSessions ? (
    <SessionsPage />
  ) : (
    <div className="page">
      {isSearch ? (
        <SearchPage
          variant={(q.get("form") ?? "a").toLowerCase() as "a" | "b" | "c"}
        />
      ) : (
        <ResultsPage />
      )}
    </div>
  );

  return (
    <ThemeContext.Provider value={theme}>
      {nav === "b" ? (
        <TrayB>{page}</TrayB>
      ) : nav === "c" ? (
        <TrayC>{page}</TrayC>
      ) : (
        <TrayA>{page}</TrayA>
      )}
      <Switcher />
    </ThemeContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
