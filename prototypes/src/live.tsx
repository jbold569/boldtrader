// #22 enhanced-view interaction prototype — LIVE over the MOCK server.
// Ruling from the user: no dependency on a running backend; the expected server
// behavior is fabricated per the contract in mockServer.ts and we prototype on
// that. The decisions this page exists to be judged against:
//
//   1. Filter/sort request strategy: request on every change vs explicit
//      submit. The request log makes every fired request observable instead of
//      guessed. `?req=immediate|submit` (immediate default; `?debounce=ms` optional).
//   2. Live events interleaving with the user's current filter/page: cards
//      updated (enrichment landed, listing ended) vs. new arrivals. Arrivals
//      prepend with a visible banner (#34). Banners are FIXED to the viewport
//      so they stay visible while scrolling the tile grid.
//   3. Empty / loading / error transitions under filters that match nothing.
//
// Display terminology: availability `dead` renders as "Ended" (user ruling);
// the wire value stays `dead` per contract #17.
// Fake-world controls (latency, error rate, event cadence) stand in for the
// real backend. Everything labeled ⚙ is a knob.

import { useCallback, useEffect, useRef, useState } from "react";
import { LISTINGS } from "./data";
import { parseFilters, patchUrl, type Filters } from "./filters";
import FilterBar from "./FilterBar";
import TileView from "./TileView";
import CondensedView from "./CondensedView";
import {
  SETTINGS,
  getResults,
  nextEvent,
  resetWorld,
  type BgEvent,
  type ResultsQuery,
} from "./mockServer";
import "./live.css";

function toQuery(f: Filters, page: number): ResultsQuery {
  const verdicts = (["match", "unsure", "not_match"] as const).filter(
    (v) => f.verdicts[v]
  );
  return {
    page,
    per_page: 8,
    verdicts,
    max_price: f.maxPrice,
    availability: f.availability,
    sort: f.sort,
  };
}

// Human-readable request line so the request strategy is visible, not inferred.
// `dead` is shown as "ended" — user-facing vocabulary.
function describeReq(q: ResultsQuery): string {
  const bits = [`page=${q.page}`];
  if (q.verdicts.length !== 3)
    bits.push(`verdict=${q.verdicts.join(",") || "none"}`);
  if (q.max_price != null) bits.push(`≤${q.max_price}`);
  if (q.availability && q.availability !== "all")
    bits.push(q.availability === "dead" ? "ended" : q.availability);
  bits.push(`sort=${q.sort}`);
  return bits.join(" ");
}

export default function LivePage() {
  const [urlQ, setUrlQ] = useState(
    () => new URLSearchParams(window.location.search)
  );
  useEffect(() => {
    const on = () => setUrlQ(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);

  const reqMode = urlQ.get("req") === "submit" ? "submit" : "immediate";
  const view = urlQ.get("view") === "condensed" ? "condensed" : "tile";
  const debounceMs = Number(urlQ.get("debounce") ?? "0") || 0;

  const [items, setItems] = useState(() => LISTINGS.slice(0, 8));
  const [total, setTotal] = useState(8);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [arrivals, setArrivals] = useState(0);
  const [livenessBanner, setLivenessBanner] = useState("");
  const [lastEvent, setLastEvent] = useState("");
  const fetchedFor = useRef(
    JSON.stringify(
      toQuery(parseFilters(new URLSearchParams(window.location.search)), 1)
    )
  );
  const [errorRate, setErrorRate] = useState(0);
  const [cadence, setCadence] = useState(SETTINGS.eventEveryMs);
  const [auto, setAuto] = useState(true);
  const [reqLog, setReqLog] = useState<string[]>([]);
  const reqCount = useRef(0);
  const [latency, setLatency] = useState(SETTINGS.latencyMs);

  const fetchPage = useCallback(
    (p: number, f: Filters, trigger = "request", silent = false) => {
      const query = toQuery(f, p);
      const key = JSON.stringify(query);
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      reqCount.current += 1;
      setReqLog((prev) =>
        [
          ...prev,
          `${new Date().toLocaleTimeString()} · ${trigger} · ${describeReq(query)}`,
        ].slice(-6)
      );
      getResults(query)
        .then(({ env, meta }) => {
          setLoading(false);
          setError(null);
          setItems(env.items);
          setTotal(meta.total);
          setPages(env.total_pages);
          setPage(env.page);
          fetchedFor.current = key;
        })
        .catch((e: unknown) => {
          setLoading(false);
          const msg =
            e && typeof e === "object" && "message" in e
              ? String((e as { message: string }).message)
              : "request failed";
          setError(msg);
        });
    },
    []
  );

  // Immediate mode: every URL (filter/page) change fires a request, optionally
  // debounced by `?debounce=ms` (default 0). This is the feel test — watch the
  // request log count climb with each filter tweak.
  useEffect(() => {
    const f = parseFilters(urlQ);
    const key = JSON.stringify(toQuery(f, page));
    if (key === fetchedFor.current) return;
    if (reqMode === "submit") return; // explicit submit only
    if (debounceMs > 0) {
      const t = setTimeout(() => fetchPage(page, f, "filter change"), debounceMs);
      return () => clearTimeout(t);
    }
    fetchPage(page, f, "filter change");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQ, page, reqMode, debounceMs]);

  const onSubmit = () => {
    const f = parseFilters(new URLSearchParams(window.location.search));
    setPage(1);
    fetchPage(1, f, "Apply click");
  };

  // Submit-mode "stale" signal: current filters differ from what's on screen.
  const dirty =
    reqMode === "submit" &&
    JSON.stringify(toQuery(parseFilters(urlQ), 1)) !== fetchedFor.current;

  // Background event stream.
  const handleEvent = useCallback((ev: BgEvent) => {
    if (ev.event === "enrichment") {
      setItems((prev) =>
        prev.map((r) =>
          r.id === ev.data.listing_id && !r.enrichment
            ? {
                ...r,
                enrichment: {
                  product: r.title.slice(0, 24),
                  condition: "complete" as const,
                  bundle: ["charger"],
                  confidence: 0.9,
                },
              }
            : r
        )
      );
      setLastEvent(`enrichment landed on ${ev.data.listing_id}`);
    } else if (ev.event === "liveness") {
      if (ev.data.dead_count > 0) {
        // dim one live card in place (the freshest end in our fixture order)
        setItems((prev) => {
          const idx = prev.findIndex((r) => r.availability === "live");
          if (idx === -1) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], availability: "dead" as const };
          return next;
        });
      }
      if (ev.data.banner) setLivenessBanner(ev.data.banner);
      setLastEvent(`liveness: ${ev.data.dead_count} ended, done=${ev.data.done}`);
    } else if (ev.event === "search_complete") {
      setArrivals((a) => a + 1);
      setLastEvent(`search_complete: ${ev.data.match_count} matches`);
    }
  }, []);

  useEffect(() => {
    if (!auto || cadence <= 0) return;
    const t = setInterval(() => handleEvent(nextEvent()), cadence);
    return () => clearInterval(t);
  }, [auto, cadence, handleEvent]);

  const setKnob = (k: "latencyMs" | "errorRate" | "eventEveryMs", v: number) => {
    SETTINGS[k] = v;
    if (k === "latencyMs") setLatency(v);
    if (k === "errorRate") setErrorRate(v);
    if (k === "eventEveryMs") setCadence(v);
  };

  const showArrivals = () => {
    const f = parseFilters(new URLSearchParams(window.location.search));
    patchUrl({ page: "1" });
    getResults(toQuery({ ...f, sort: "newest" }, 1)).then(({ env, meta }) => {
      setItems(env.items);
      setTotal(meta.total);
      setPages(env.total_pages);
      setPage(1);
      setArrivals(0);
      setReqLog((prev) =>
        [
          ...prev,
          `${new Date().toLocaleTimeString()} · arrivals merge · sort=newest page=1`,
        ].slice(-6)
      );
    });
  };

  return (
    <div className="lv">
      {/* Banners pinned to the viewport: tile-view scrolling never hides them. */}
      <div className="lv-fixed">
        {error && (
          <div className="lv-error" role="alert">
            <strong>Request failed:</strong> {error}{" "}
            <button
              onClick={() =>
                fetchPage(
                  page,
                  parseFilters(new URLSearchParams(window.location.search)),
                  "Retry"
                )
              }
            >
              Retry
            </button>
          </div>
        )}
        {arrivals > 0 && (
          <button className="lv-arrivals" onClick={showArrivals}>
            ▲ {arrivals} new listing{arrivals > 1 ? "s" : ""} — tap to add to top
          </button>
        )}
        {livenessBanner && (
          <div className="lv-liveness">{livenessBanner}</div>
        )}
      </div>

      <div className="lv-panel">
        <span className="lv-panel-title">⚙ fake server</span>
        <label>
          latency{" "}
          <select value={latency} onChange={(e) => setKnob("latencyMs", Number(e.target.value))}>
            <option value={0}>0 ms</option>
            <option value={90}>90 ms</option>
            <option value={300}>300 ms</option>
            <option value={1200}>1200 ms</option>
          </select>
        </label>
        <label>
          errors{" "}
          <select
            value={errorRate}
            onChange={(e) => setKnob("errorRate", Number(e.target.value))}
          >
            <option value={0}>clean</option>
            <option value={0.4}>flaky 40%</option>
            <option value={1}>always 500</option>
          </select>
        </label>
        <label>
          events{" "}
          <select
            value={cadence}
            onChange={(e) => setKnob("eventEveryMs", Number(e.target.value))}
          >
            <option value={0}>off</option>
            <option value={1500}>1.5 s</option>
            <option value={4000}>4 s</option>
            <option value={10000}>10 s</option>
          </select>
        </label>
        <label>
          request
          <select value={reqMode} onChange={(e) => patchUrl({ req: e.target.value })}>
            <option value="immediate">on every change</option>
            <option value="submit">explicit submit</option>
          </select>
        </label>
        <button onClick={() => setAuto((a) => !a)} aria-pressed={auto}>
          {auto ? "⏸ pause stream" : "▶ resume stream"}
        </button>
        <button onClick={() => handleEvent(nextEvent())}>+ inject one event</button>
        <button onClick={() => patchUrl({ verdict: "none" })}>
          filter matches nothing
        </button>
        <span className="lv-event" aria-live="polite">
          {lastEvent || "—"}
        </span>
      </div>

      {reqMode === "submit" && (
        <div className={`lv-submit${dirty ? " lv-dirty" : ""}`}>
          <button onClick={onSubmit}>Apply filters</button>
          <span className="muted">
            {dirty
              ? "filters changed — results on screen are stale until you click."
              : "explicit-submit mode: nothing fetches until you click."}
          </span>
        </div>
      )}

      <div className="lv-reqlog" aria-live="polite">
        <strong>requests fired: {reqCount.current}</strong>
        {reqLog.length > 0 && (
          <ul>
            {reqLog.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        )}
      </div>

      <FilterBar count={total} />

      {loading ? (
        <div className="lv-loading">
          <div className="lv-skel" />
          <div className="lv-skel" />
          <div className="lv-skel" />
          <span className="muted">loading… ({latency} ms fake latency)</span>
        </div>
      ) : items.length === 0 ? (
        <div className="lv-empty">
          <p>
            <strong>Nothing matches these filters.</strong>
          </p>
          <p className="muted">
            {total} results for this search overall — your filter combination
            excludes everything.
          </p>
          <button onClick={() => patchUrl({ verdict: null, max_price: null, availability: null })}>
            Clear filters
          </button>
        </div>
      ) : view === "tile" ? (
        <TileView listings={items} />
      ) : (
        <CondensedView listings={items} />
      )}

      <div className="lv-pager">
        <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          ← prev
        </button>
        <span>
          page {page} / {pages} · {total} results
        </span>
        <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
          next →
        </button>
      </div>

      <div className="lv-scenarios">
        <span className="lv-panel-title">⚙ world reset</span>
        <button
          onClick={() =>
            (
              resetWorld(),
              setItems(LISTINGS.slice(0, 8)),
              setArrivals(0),
              setLivenessBanner(""),
              setError(null),
              setReqLog([]),
              (reqCount.current = 0),
              patchUrl({})
            )
          }
        >
          reset fake world
        </button>
      </div>
    </div>
  );
}
