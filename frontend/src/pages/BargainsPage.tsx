// Bargain Search list page (ticket #44): paginated list of saved Bargain
// Searches with a create modal over the list. Pagination lives in the URL
// query string (`?page=N`) so it survives reload and back/forward; the
// params are the query key.

import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createSearch, deleteSearch, listSearches } from "../api/client";
import SearchForm from "../components/SearchForm";
import "./bargains.css";

export default function BargainsPage() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") || 1));
  const [open, setOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["searches", { page }],
    queryFn: () => listSearches(page),
  });

  const goto = (p: number) => setParams(p > 1 ? { page: String(p) } : {});

  const onCreate = async (draft: Parameters<typeof createSearch>[0]) => {
    setServerError(null);
    try {
      await createSearch(draft);
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["searches"] });
    } catch (e) {
      // A failed submit keeps every filled value in place: the form stays
      // mounted with its state; the server message names the offending field.
      setServerError(e instanceof Error ? e.message : String(e));
    }
  };

  const onDelete = async (id: number, summary: string) => {
    if (!window.confirm(`Delete "${summary}"? Its results go with it.`)) return;
    try {
      await deleteSearch(id);
      queryClient.invalidateQueries({ queryKey: ["searches"] });
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="bargains page">
      <div className="bl-head">
        <h1>Bargain Searches</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          + New Bargain Search
        </button>
      </div>

      {isLoading && <p className="muted">Loading…</p>}
      {error && (
        <p className="bl-error">
          Couldn't load the list: {error instanceof Error ? error.message : error}
        </p>
      )}
      {data && data.items.length === 0 && (
        <p className="muted">
          No Bargain Searches yet. Create one, or build it through{" "}
          <Link to="/">chat</Link>.
        </p>
      )}

      {data && data.items.length > 0 && (
        <>
          <ul className="bl-list">
            {data.items.map((s) => (
              <li key={s.id} className="bl-row card">
                <Link className="bl-summary" to={`/bargains/${s.id}`}>
                  {s.summary}
                </Link>
                <span className="bl-meta">
                  <span className="chip">{s.status}</span>
                  <span className="muted">
                    {s.match_count.toLocaleString()} matches
                  </span>
                  <span className="muted">updated {s.updated_at.slice(0, 16)}</span>
                  <button
                    className="bl-del"
                    aria-label={`Delete ${s.summary}`}
                    onClick={() => onDelete(s.id, s.summary)}
                  >
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <nav className="bl-pager" aria-label="pages">
            <button
              disabled={page <= 1}
              onClick={() => goto(page - 1)}
              aria-label="Previous page"
            >
              ← Prev
            </button>
            <span className="muted">
              page {data.page} of {data.total_pages} ({data.total} total)
            </span>
            <button
              disabled={page >= data.total_pages}
              onClick={() => goto(page + 1)}
              aria-label="Next page"
            >
              Next →
            </button>
          </nav>
        </>
      )}

      {open && (
        <div className="mdl-scrim" onClick={() => setOpen(false)}>
          <div
            className="mdl"
            role="dialog"
            aria-label="New Bargain Search"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mdl-head">
              <h2>New Bargain Search</h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setOpen(false)}
              >
                ✕
              </button>
            </div>
            <div className="mdl-body">
              <SearchForm
                onSubmit={onCreate}
                submitting={false}
                serverError={serverError}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
