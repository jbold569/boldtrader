// #22 enhanced-view interaction prototype — LIVE over the MOCK server.
// Ruling from the user: no dependency on a running backend; the expected server
// behavior is fabricated per the contract in mockServer.ts and we prototype on
// that. The decisions this page exists to be judged against:
//
//   1. Filter/sort request strategy: does a request per filter change feel
//      instant, or is debounce/explicit submit needed? Toggle `?req=`.
//   2. Live events interleaving with the user's current filter/page: cards
//      updated (enrichment landed, liveness died) vs. new arrivals. Per the
//      #34 decision, arrivals PREPEND with a visible banner — this page shows
//      exactly that so you can judge if it reads as alive or as broken.
//   3. Empty / loading / error transitions under filters that match nothing.
//
// Fake-world controls (latency, error rate, event cadence, scripted injections)
// stand in for whatever the real backend does. Everything labeled ⚙ is a knob.

import { useCallback, useEffect, useRef, useState } from "react";
import { LISTINGS } from "./data";
import { parseFilters, patchUrl, type Filters } from "./filters";
import FilterBar from "./FilterBar";
import TileView from "./TileView";
import CondensedView from "./CondensedView";
import {
  SETTINGS,
  getResults,
  rejectListing,
  reenrich,
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

export default function LivePage() {
  const q0 = new URLSearchParams(window.location.search);
  const reqMode = q0.get("req") === "submit" ? "submit" : "immediate";
  const view = q0.get("view") === "condensed" ? "condensed" : "tile";

  const [items, setItems] = useState(() => LISTINGS.slice(0, 8));
  const [total, setTotal] = useState(8);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [arrivals, setArrivals] = useState(0);
  const [livenessBanner, setLivenessBanner] = useState("");
  const [lastEvent, setLastEvent] = useState("");
  const [latency, setLatency] = useState(SETTINGS.latencyMs);
  const [errorRate, setErrorRate] = useState(0);
  const [cadence, setCadence] = useState(SETTINGS.eventEveryMs);
  const [auto, setAuto] = useState(true);
  const fetchedFor = useRef("");

  const fetchPage = useCallback(
    (p: number, f: Filters, silent = false) => {
      const key = JSON.stringify([toQuery(f, p)]);
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      getResults(toQuery(f, p))
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
  // debounced by `?debounce=ms` (default 0). This is the feel test.
  const debounceMs = Number(q0.get("debounce") ?? "0") || 0;
  useEffect(() => {
    const f = parseFilters(new URLSearchParams(window.location.search));
    const key = JSON.stringify([toQuery(f, page)]);
    if (key === fetchedFor.current) return;
    if (reqMode === "submit") return; // explicit submit only
    if (debounceMs > 0) {
      const t = setTimeout(() => fetchPage(page, f), debounceMs);
      return () => clearTimeout(t);
    }
    fetchPage(page, f);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window.location.search, page, reqMode, debounceMs]);

  const onSubmit = () => {
    const f = parseFilters(new URLSearchParams(window.location.search));
    fetchPage(1, f);
  };

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
        // dim one live card in place (the freshest death in our fixture order)
        setItems((prev) => {
          const idx = prev.findIndex((r) => r.availability === "live");
          if (idx === -1) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], availability: "dead" as const };
          return next;
        });
      }
      if (ev.data.banner) setLivenessBanner(ev.data.banner);
      setLastEvent(`liveness: ${ev.data.dead_count} dead, done=${ev.data.done}`);
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

  const doReject = (id: string) =>
    rejectListing(id, "user rejected").then(() =>
      setItems((prev) =>
        prev.map((r) =>
          r.id === id ? { ...r, availability: "dead" as const } : r
        )
      )
    );

  const showArrivals = () => {
    const f = parseFilters(new URLSearchParams(window.location.search));
    patchUrl({ page: "1" });
    getResults(toQuery({ ...f, sort: "newest" }, 1)).then(({ env, meta }) => {
      setItems(env.items);
      setTotal(meta.total);
      setPages(env.total_pages);
      setPage(1);
      setArrivals(0);
    });
  };

  const scenario = (name: string) => {
    if (name === "empty") patchUrl({ verdict: "none" });
    if (name === "err") setKnob("errorRate", 1), setErrorRate(1);
    if (name === "flaky") setErrorRate(0.4), (SETTINGS.errorRate = 0.4);
    if (name === "clean") setErrorRate(0), (SETTINGS.errorRate = 0);
    if (name === "slow") setKnob("latencyMs", 1200), setLatency(1200);
    if (name === "fast") setKnob("latencyMs", 90), setLatency(90);
    if (name === "reset")
      resetWorld(),
        setItems(LISTINGS.slice(0, 8)),
        setArrivals(0),
        setLivenessBanner(""),
        setError(null),
        patchUrl({});
  };

  return (
    <div className="lv">
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
        <button onClick={() => setAuto((a) => !a)} aria-pressed={auto}>
          {auto ? "⏸ pause stream" : "▶ resume stream"}
        </button>
        <button onClick={() => handleEvent(nextEvent())}>+ inject one event</button>
        <span className="lv-event" aria-live="polite">
          {lastEvent || "—"}
        </span>
      </div>

      {error && (
        <div className="lv-error" role="alert">
          <strong>Request failed:</strong> {error}{" "}
          <button onClick={() => fetchPage(page, parseFilters(new URLSearchParams(window.location.search)))}>
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

      {reqMode === "submit" && (
        <div className="lv-submit">
          <button onClick={onSubmit}>Apply filters</button>
          <span className="muted">explicit-submit mode: nothing fetches until you click.</span>
        </div>
      )}

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
        <span className="lv-panel-title">⚙ scenarios</span>
        <button onClick={() => scenario("empty")}>filter matches nothing</button>
        <button onClick={() => scenario("err")}>force error</button>
        <button onClick={() => scenario("flaky")}>flaky backend</button>
        <button onClick={() => scenario("clean")}>clean backend</button>
        <button onClick={() => scenario("slow")}>slow backend</button>
        <button onClick={() => scenario("fast")}>fast backend</button>
        <button
          onClick={() => {
            reenrich().then((r) =>
              setLastEvent(`reenrichment requeued ${r.requeued}`)
            );
          }}
        >
          re-enrich all pending
        </button>
        <button
          onClick={() => doReject(items[0]?.id ?? "")}
          disabled={!items.length}
        >
          reject first card
        </button>
      </div>
    </div>
  );
}
