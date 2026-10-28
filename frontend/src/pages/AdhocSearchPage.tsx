// Ad-hoc Marketplace Search (ticket #48): one horizontal row — Search box,
// Marketplace select, Location, Search button — with the raw Listings
// rendered inline below as a paginated ListingCard grid. The URL query
// string IS the query key (`q`, `marketplace`, `location`, `page`): a
// reload repeats the same search, back/forward walks through past searches.
// Validation is submit-time only — typing never re-queries. Nothing is
// saved; browsing never touches the Listing Store.
//
// Query key: `["adhoc", params]` rather than the doc's illustrative
// `["search", params]` — that key is already spoken for by the Bargain
// Search GET in #45, and two different payloads under one key name is a
// trap worth dodging.

import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { marketplaceSearch } from "../api/client";
import ListingCard from "../components/ListingCard";
import { patchSearch } from "../filters";
import {
  MARKETPLACE_OPTIONS,
  parseAdhoc,
  validateAdhoc,
  type AdhocForm,
} from "../adhoc";
import "../components/adhoc.css";

export default function AdhocSearchPage() {
  const [params, setParams] = useSearchParams();
  // The URL answers the query; the form is just in-progress input (#48:
  // nothing persists beyond the URL, so the two are re-synced only at
  // submit, never per keystroke).
  const query = parseAdhoc(params);
  const [form, setForm] = useState<AdhocForm>(() => ({
    q: query.q,
    marketplace: query.marketplace,
    location: query.location,
  }));
  const [errs, setErrs] = useState<Record<string, string>>({});

  const results = useQuery({
    queryKey: ["adhoc", query],
    queryFn: () =>
      marketplaceSearch({
        q: query.q,
        marketplace: query.marketplace,
        location: query.location,
        page: query.page,
      }),
    // An empty q would ask the server for its own fallback query; the
    // page simply doesn't search until there's something to search for.
    enabled: query.q !== "",
    placeholderData: keepPreviousData,
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const found = validateAdhoc(form);
    setErrs(found);
    if (Object.keys(found).length > 0) return;
    // A new search starts on page 1; the old page pointer is dropped.
    setParams(patchSearch("", { ...form }));
  };

  const goto = (p: number) =>
    setParams(patchSearch(params, { page: p <= 1 ? null : p }));

  const data = results.data;
  const failed = data?.failed_marketplaces ?? [];

  return (
    <section className="as">
      <form className="as-row" onSubmit={submit}>
        <label className="fd">
          <span className="fd-label">Search</span>
          <input
            value={form.q}
            onChange={(e) => setForm((f) => ({ ...f, q: e.target.value }))}
            placeholder="gaming pc, ddr4, thinkstation…"
            enterKeyHint="search"
            aria-invalid={errs.q ? true : undefined}
          />
          {errs.q && <span className="fd-err">{errs.q}</span>}
        </label>
        <label className="fd">
          <span className="fd-label">Marketplace</span>
          <select
            value={form.marketplace}
            onChange={(e) =>
              setForm((f) => ({ ...f, marketplace: e.target.value }))
            }
          >
            {MARKETPLACE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="fd">
          <span className="fd-label">Location</span>
          <input
            value={form.location}
            onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
            placeholder="City, State"
            aria-invalid={errs.location ? true : undefined}
          />
          {errs.location && <span className="fd-err">{errs.location}</span>}
        </label>
        <button type="submit" className="btn-primary as-go">
          Search
        </button>
      </form>

      {query.q === "" && (
        <p className="muted as-empty">
          Type what you're after — an ad-hoc Marketplace query, nothing gets
          saved.
        </p>
      )}

      {results.isError && (
        <p className="as-error">
          Search failed:{" "}
          {results.error instanceof Error ? results.error.message : results.error}
        </p>
      )}

      {failed.length > 0 && (
        <div className="as-warn" role="status">
          {failed.join(", ")} failed to respond — showing{" "}
          {query.marketplace === "all" ? "the rest" : "what came back"} only.
        </div>
      )}

      {data && (
        <>
          <p className="as-count muted">
            {data.total.toLocaleString()} listings · page {query.page} of{" "}
            {data.total_pages}
          </p>
          {data.items.length === 0 ? (
            <p className="muted as-empty">Nothing matched. Try fewer words.</p>
          ) : (
            <div className="lc-grid">
              {data.items.map((card) => (
                <ListingCard key={card.id} card={card} />
              ))}
            </div>
          )}
          <nav className="as-pager" aria-label="pages">
            <button
              disabled={query.page <= 1}
              onClick={() => goto(query.page - 1)}
              aria-label="Previous page"
            >
              ← Prev
            </button>
            <button
              disabled={query.page >= data.total_pages}
              onClick={() => goto(query.page + 1)}
              aria-label="Next page"
            >
              Next →
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
