// Filter/sort bar (ticket #46), shared by the Search Results view. Every
// control writes straight to the URL — the URL is the query key
// (docs/frontend-architecture.md); no filter state lives here beyond the
// in-progress max-price draft. Style settled in prototypes/src/FilterBar.
//
// Changes go in with replace:true (the prototype's replaceState ruling): a
// filter tweak rewrites the current history entry instead of stacking one
// per click, so Back leaves the page rather than unwinding twelve filters.

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  type SortKey,
  type Verdict,
  VERDICT_KEYS,
  VERDICT_LABELS,
  DEFAULT_WIRE_VERDICT,
  patchSearch,
  parseFilters,
} from "../filters";
import "./filterbar.css";

export default function FilterBar({ count }: { count: number }) {
  const [params, setParams] = useSearchParams();
  const f = parseFilters(params);
  const urlMax = params.get("max_price");
  const [priceDraft, setPriceDraft] = useState("");
  // Keep the draft honest when the URL moves under us (Clear filters,
  // back/forward) without clobbering in-progress typing.
  useEffect(() => setPriceDraft(urlMax ?? ""), [urlMax]);

  // Any filter change narrows to a different first page: reset page too.
  const write = (updates: Record<string, string | null>) => {
    setParams(patchSearch(params, { ...updates, page: null }), { replace: true });
  };

  const setVerdict = (v: Verdict, on: boolean) => {
    const verdicts = { ...f.verdicts, [v]: on };
    const selected = VERDICT_KEYS.filter((k) => verdicts[k]);
    if (selected.length === 0) write({ verdict: "none" });
    else {
      const joined = selected.join(",");
      // The default selection means "absent" on the URL.
      if (joined === DEFAULT_WIRE_VERDICT) write({ verdict: null });
      else write({ verdict: joined });
    }
  };

  const applyPrice = () => {
    const t = priceDraft.trim();
    const n = Number(t);
    const valid = t !== "" && Number.isFinite(n) && n >= 0;
    write(valid ? { max_price: String(n) } : { max_price: null });
  };

  return (
    <div className="fb">
      <div className="fb-verdicts" role="group" aria-label="Verdicts">
        {VERDICT_KEYS.map((v) => (
          <label key={v} className={`fb-check${f.verdicts[v] ? " on" : ""}`}>
            <input
              type="checkbox"
              checked={f.verdicts[v]}
              onChange={(e) => setVerdict(v, e.target.checked)}
            />
            {VERDICT_LABELS[v]}
          </label>
        ))}
      </div>
      <div className="fb-field">
        <label htmlFor="fb-max">Max price</label>
        <input
          id="fb-max"
          inputMode="decimal"
          value={priceDraft}
          onChange={(e) => setPriceDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && applyPrice()}
          placeholder="$"
        />
        <button onClick={applyPrice}>Apply</button>
      </div>
      <div className="fb-field">
        <label htmlFor="fb-avail">Availability</label>
        <select
          id="fb-avail"
          value={f.availability}
          onChange={(e) =>
            write({
              availability:
                e.target.value === "all" ? null : e.target.value as string,
            })
          }
        >
          <option value="all">All</option>
          <option value="live">Live</option>
          <option value="dead">Ended</option>
        </select>
      </div>
      <div className="fb-field">
        <label htmlFor="fb-sort">Sort</label>
        <select
          id="fb-sort"
          value={f.sort}
          onChange={(e) =>
            write({
              sort: e.target.value === "newest" ? null : (e.target.value as SortKey),
            })
          }
        >
          <option value="newest">Newest</option>
          <option value="price_asc">Price ↑</option>
          <option value="price_desc">Price ↓</option>
        </select>
      </div>
      <div className="fb-count" aria-live="polite">
        {count.toLocaleString()} results
      </div>
    </div>
  );
}
