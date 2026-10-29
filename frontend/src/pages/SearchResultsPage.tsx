// Search Results view (tickets #45, #46): the per-Bargain-Search board —
// always-visible filter/sort bar, ResultCard grid, liveness banner, and the
// edit modal (SearchForm → PATCH). The URL query string IS the query key:
// the filtered view is shareable and survives reload; filter changes replace
// the history entry (Back leaves the page rather than unwinding twelve
// tweaks) while the pager pushes as normal.
//
// Live behaviour: the rendered grid is frozen in local state so incoming
// listings never re-shift content under the reader's scroll. `enrichment`
// events pull a silent first page and queue the newcomers behind a
// viewport-sticky "▲ N new listings" banner; the reader adopts on the
// banner or at the bottom sentinel. Adopting also happens automatically
// whenever the URL query itself changes — that is user intent, not a
// surprise. Ended listings dim in place straight off the liveness payload.

import { useEffect, useRef, useState } from "react";
import { useSearchParams, useParams } from "react-router-dom";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { getLiveness, getResults, getSearch, updateSearch } from "../api/client";
import type { ResultCard as ResultCardData } from "../api/types";
import {
  VERDICT_KEYS,
  buildQuery,
  buildSearch,
  parseDensity,
  patchSearch,
  parseFilters,
} from "../filters";
import FilterBar from "../components/FilterBar";
import ResultCard from "../components/ResultCard";
import CondensedView from "../components/CondensedView";
import SearchForm from "../components/SearchForm";
import { useEvents } from "../components/EventsProvider";
import "../components/results.css";

interface View {
  key: string;
  items: ResultCardData[];
}

export default function SearchResultsPage() {
  const { id } = useParams<{ id: string }>();
  const searchId = Number(id);
  const [editOpen, setEditOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const filters = parseFilters(params);
  const wireKey = buildSearch(filters);
  // Density rides the same URL (#47) but is deliberately NOT in the wire
  // query: flipping tile ⇄ condensed never changes the query key, so it
  // never refetches.
  const density = parseDensity(params);
  const hasVerdicts = VERDICT_KEYS.some((k) => filters.verdicts[k]);

  const search = useQuery({
    queryKey: ["search", searchId],
    queryFn: () => getSearch(searchId),
    enabled: Number.isFinite(searchId),
  });
  const results = useQuery({
    queryKey: ["results", searchId, wireKey],
    queryFn: () => getResults(searchId, buildQuery(filters)),
    enabled: Number.isFinite(searchId) && hasVerdicts,
    // A failed refetch keeps the grid on screen instead of blanking it
    // (#46: error banner over visible content).
    placeholderData: keepPreviousData,
  });
  const liveness = useQuery({
    queryKey: ["liveness", searchId],
    queryFn: () => getLiveness(searchId),
    enabled: Number.isFinite(searchId),
    // The liveness event over the SSE stream normally tells us the sweep
    // finished; the poll is the belt-and-braces fallback while it runs.
    refetchInterval: (q) => (q.state.data && !q.state.data.done ? 5000 : false),
  });

  // Frozen grid + queued arrivals.
  const [view, setView] = useState<View | null>(null);
  const [pending, setPending] = useState<ResultCardData[]>([]);
  const viewRef = useRef<View | null>(null);
  viewRef.current = view;
  const lastFresh = useRef<{ key: string; items: ResultCardData[] } | null>(null);

  // Adopt whatever the current query just returned.
  useEffect(() => {
    const data = results.data;
    // Only adopt data that actually answers the current query: with
    // keepPreviousData, `results.data` can be the previous page's
    // placeholder while the new one is still in flight.
    if (!data || results.isPlaceholderData || view?.key === wireKey) return;
    setView({ key: wireKey, items: data.items });
    setPending([]);
  }, [results.data, results.isPlaceholderData, wireKey, view]);

  // Silent arrival pull: newest-first page 1 diffed against what is on
  // screen. Throttled — a fan-out fires one enrichment event per listing
  // and each pull is the same request.
  const pullRef = useRef<() => void>(() => {});
  pullRef.current = async () => {
    if (!Number.isFinite(searchId) || !hasVerdicts) return;
    const f = { ...parseFilters(window.location.search), page: 1 };
    try {
      const fresh = await getResults(searchId, buildQuery(f));
      lastFresh.current = { key: buildSearch(f), items: fresh.items };
      const shown = new Set(viewRef.current?.items.map((c) => c.listing_id));
      const arrivals = fresh.items.filter((c) => !shown.has(c.listing_id));
      if (arrivals.length) {
        setPending((prev) => {
          const seen = new Set(prev.map((c) => c.listing_id));
          return [...arrivals.filter((c) => !seen.has(c.listing_id)), ...prev];
        });
      }
    } catch {
      // Background refresh; the next event or a manual retry covers it.
    }
  };

  const timerRef = useRef<number | undefined>(undefined);
  const pullSoon = () => {
    if (timerRef.current !== undefined) return;
    timerRef.current = window.setTimeout(() => {
      timerRef.current = undefined;
      void pullRef.current();
    }, 1500);
  };
  useEffect(() => () => clearTimeout(timerRef.current), []);

  const events = useEvents();
  useEffect(() => {
    const offEnrichment = events.on("enrichment", pullSoon);
    // Tail of the fan-out: one more pull so the last enrichments are never
    // left behind by the throttle window.
    const offComplete = events.on("search_complete", (e) => {
      if (e.search_id === searchId) void pullRef.current();
    });
    return () => {
      offEnrichment();
      offComplete();
    };
  }, [events, searchId]);

  const adopt = () => {
    const fresh = lastFresh.current;
    if (!fresh) return;
    setView(fresh);
    setPending([]);
    if (params.get("page")) {
      setParams(patchSearch(params, { page: null }), { replace: true });
    }
    window.scrollTo({ top: 0 });
  };

  // Bottom sentinel: reaching the end of the frozen grid adopts the queue.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const adoptRef = useRef(adopt);
  adoptRef.current = adopt;
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || pending.length === 0) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((en) => en.isIntersecting)) adoptRef.current();
    });
    io.observe(el);
    return () => io.disconnect();
  }, [pending.length]);

  // Ended listings dim in place (#46): straight off the liveness payload,
  // no banner, the card's own "Ended" chip + dimmed style do the talking.
  const dead = liveness.data?.done ? liveness.data.dead : [];
  const shownItems = dead.length
    ? (view?.items ?? []).map((c) =>
        dead.includes(c.listing_id) ? { ...c, availability: "dead" } : c,
      )
    : (view?.items ?? []);

  const goto = (p: number) => {
    setParams(patchSearch(params, { page: p <= 1 ? null : p }));
  };

  // Clearing filters clears the query, not the density choice (#47).
  const clearFilters = () =>
    setParams(
      new URLSearchParams(density === "condensed" ? { view: "condensed" } : {}),
      { replace: true },
    );

  const onSaveEdit = async (draft: Parameters<typeof updateSearch>[1]) => {
    setServerError(null);
    try {
      await updateSearch(searchId, draft);
      setEditOpen(false);
      // The PATCH bumps version + kicks a new fan-out; drop the frozen
      // grid so the adopt effect replaces it, and pull the fresh search,
      // its results, and the restarted sweep.
      setView(null);
      setPending([]);
      queryClient.invalidateQueries({ queryKey: ["search", searchId] });
      queryClient.invalidateQueries({ queryKey: ["results", searchId] });
    } catch (e) {
      setServerError(e instanceof Error ? e.message : String(e));
    }
  };

  // The edit form opens pre-filled from the current search, fresh each
  // open: the key (version-scoped) forces a remount so stale edits never
  // carry over.
  const draftFromSearch = search.data && {
    summary: search.data.summary,
    product_identity: search.data.product_identity,
    target_price:
      search.data.target_price === null ? "" : String(search.data.target_price),
    location: search.data.location ?? "",
    queries: search.data.queries,
    exclusions: search.data.exclusions,
  };


  const empty = hasVerdicts
    ? view !== null && view.items.length === 0
    : true;

  return (
    <section className="sr">
      <div className="sr-head">
        <div>
          <h1>{search.data?.summary ?? `Bargain Search #${searchId}`}</h1>
          <div className="sr-meta">
            {search.data && (
              <>
                <span className="chip">{search.data.status}</span>
                <span>
                  {search.data.match_count.toLocaleString()} matches · v
                  {search.data.version}
                </span>
              </>
            )}
            <button onClick={() => setEditOpen(true)}>Edit</button>
          </div>
        </div>
      </div>
      <FilterBar count={results.data?.total ?? 0} />

      {(results.isError || pending.length > 0) && (
        <div className="sr-fixed">
          {results.isError && (
            <div className="sr-errbar" role="alert">
              <strong>Couldn&apos;t refresh results:</strong>{" "}
              {results.error instanceof Error
                ? results.error.message
                : String(results.error)}{" "}
              <button onClick={() => void results.refetch()}>Retry</button>
            </div>
          )}
          {pending.length > 0 && (
            <button className="sr-arrivals" onClick={adopt}>
              ▲ {pending.length} new listing
              {pending.length === 1 ? "" : "s"} — tap to add to top
            </button>
          )}
        </div>
      )}

      {results.isLoading && <p className="muted">Loading results…</p>}

      {empty ? (
        <div className="sr-empty">
          <p>No listings match these filters.</p>
          <button onClick={clearFilters}>Clear filters</button>
        </div>
      ) : (
        <>
          {density === "condensed" ? (
            <CondensedView items={shownItems} searchId={searchId} />
          ) : (
            <div className="rc-grid">
              {shownItems.map((card) => (
                <ResultCard
                  key={card.listing_id}
                  card={card}
                  searchId={searchId}
                />
              ))}
            </div>
          )}
          <div ref={sentinelRef} aria-hidden="true" />
          <nav className="bl-pager" aria-label="pages">
            <button
              disabled={filters.page <= 1}
              onClick={() => goto(filters.page - 1)}
              aria-label="Previous page"
            >
              ← Prev
            </button>
            <span className="muted">
              page {results.data?.page ?? filters.page} of{" "}
              {results.data?.total_pages ?? 1} (
              {results.data?.total ?? 0} total)
            </span>
            <button
              disabled={
                !results.data || filters.page >= results.data.total_pages
              }
              onClick={() => goto(filters.page + 1)}
              aria-label="Next page"
            >
              Next →
            </button>
          </nav>
        </>
      )}

      {editOpen && draftFromSearch && (
        <div className="mdl-scrim" onClick={() => setEditOpen(false)}>
          <div
            className="mdl"
            role="dialog"
            aria-label="Edit Bargain Search"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mdl-head">
              <h2>Edit Bargain Search</h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setEditOpen(false)}
              >
                ✕
              </button>
            </div>
            <div className="mdl-body">
              <SearchForm
                key={`edit-${searchId}-${search.data?.version ?? 0}`}
                initial={draftFromSearch}
                onSubmit={onSaveEdit}
                submitting={false}
                serverError={serverError}
                submitLabel="Save changes"
                onCancel={() => setEditOpen(false)}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
