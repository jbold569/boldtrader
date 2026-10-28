// Search Results view (ticket #45): the per-Bargain-Search board —
// liveness banner + ResultCard grid + the edit modal (SearchForm → PATCH).
// The contract's default result view is match,unsure; filters live in the
// URL query string and are read here so links (and #46's filter bar)
// drive the query directly.

import { useState } from "react";
import { Link, useSearchParams, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getLiveness, getResults, getSearch, updateSearch } from "../api/client";
import ResultCard from "../components/ResultCard";
import SearchForm from "../components/SearchForm";
import "../components/results.css";

export default function SearchResultsPage() {
  const { id } = useParams<{ id: string }>();
  const searchId = Number(id);
  const [editOpen, setEditOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") || 1));
  const filters = {
    page,
    verdict: params.get("verdict") || undefined,
    max_price: params.get("max_price") ? Number(params.get("max_price")) : undefined,
    availability:
      (params.get("availability") as "live" | "dead" | null) || undefined,
    sort:
      (params.get("sort") as "price_asc" | "price_desc" | "newest" | null) ||
      undefined,
  };

  const search = useQuery({
    queryKey: ["search", searchId],
    queryFn: () => getSearch(searchId),
    enabled: Number.isFinite(searchId),
  });
  const results = useQuery({
    queryKey: ["results", searchId, filters],
    queryFn: () => getResults(searchId, filters),
    enabled: Number.isFinite(searchId),
  });
  const liveness = useQuery({
    queryKey: ["liveness", searchId],
    queryFn: () => getLiveness(searchId),
    enabled: Number.isFinite(searchId),
    // The liveness event over the SSE stream normally tells us the sweep
    // finished; the poll is the belt-and-braces fallback while it runs.
    refetchInterval: (q) => (q.state.data && !q.state.data.done ? 5000 : false),
  });

  const goto = (p: number) => {
    const next = new URLSearchParams(params);
    if (p <= 1) next.delete("page");
    else next.set("page", String(p));
    setParams(next);
  };

  const onSaveEdit = async (draft: Parameters<typeof updateSearch>[1]) => {
    setServerError(null);
    try {
      await updateSearch(searchId, draft);
      setEditOpen(false);
      // The PATCH bumps version + kicks a new fan-out; pull the fresh
      // search, its results, and the restarted sweep.
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

  const lv = liveness.data;
  const banner =
    lv && !lv.done ? (
      <div className="lv-banner" role="status">
        Checking listing liveness…
      </div>
    ) : lv?.banner ? (
      <div className="lv-banner" role="alert">
        {lv.banner}
      </div>
    ) : lv ? (
      <div className="lv-banner lv-ok" role="status">
        Liveness checked
        {lv.dead.length
          ? ` — ${lv.dead.length} listing${lv.dead.length === 1 ? "" : "s"} ended`
          : " — all listings live"}
        .
      </div>
    ) : null;

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

      {banner}

      {results.isLoading && <p className="muted">Loading results…</p>}
      {results.error && (
        <p className="sr-error">
          Couldn't load results:{" "}
          {results.error instanceof Error ? results.error.message : results.error}{" "}
          <Link to="/bargains">Back to the list</Link>
        </p>
      )}

      {results.data && (
        <>
          {results.data.items.length === 0 ? (
            <p className="muted">No results on this page.</p>
          ) : (
            <div className="rc-grid">
              {results.data.items.map((card) => (
                <ResultCard
                  key={card.listing_id}
                  card={card}
                  searchId={searchId}
                />
              ))}
            </div>
          )}
          <nav className="bl-pager" aria-label="pages">
            <button disabled={page <= 1} onClick={() => goto(page - 1)} aria-label="Previous page">
              ← Prev
            </button>
            <span className="muted">
              page {results.data.page} of {results.data.total_pages} (
              {results.data.total} total)
            </span>
            <button
              disabled={page >= results.data.total_pages}
              onClick={() => goto(page + 1)}
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
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
