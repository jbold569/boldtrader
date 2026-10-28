// Shared filter/sort bar mounted at the top of both result views (tile and
// condensed). Every control writes straight to the URL — same state contract as
// GET /searches/{id}/results, so the two views are two renders of one query.

import { useEffect, useState } from "react";
import {
  type Filters,
  type Verdict,
  type SortKey,
  type Availability,
  VERDICT_KEYS,
  VERDICT_LABELS,
  parseFilters,
  serializeVerdicts,
  patchUrl,
} from "./filters";
import "./filterbar.css";

export default function FilterBar({ count }: { count: number }) {
  const [f, setF] = useState<Filters>(() =>
    parseFilters(new URLSearchParams(window.location.search))
  );
  const [priceDraft, setPriceDraft] = useState(
    () => new URLSearchParams(window.location.search).get("max_price") ?? ""
  );

  useEffect(() => {
    const sync = () =>
      setF(parseFilters(new URLSearchParams(window.location.search)));
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const setVerdict = (v: Verdict, on: boolean) => {
    const verdicts = { ...f.verdicts, [v]: on };
    patchUrl({ verdict: serializeVerdicts(verdicts) });
  };

  const applyPrice = () => {
    const n = Number(priceDraft);
    patchUrl(
      priceDraft.trim() !== "" && Number.isFinite(n) && n >= 0
        ? { max_price: String(n) }
        : { max_price: null }
    );
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
            patchUrl({ availability: e.target.value as Availability })
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
          onChange={(e) => patchUrl({ sort: e.target.value as SortKey })}
        >
          <option value="newest">Newest</option>
          <option value="price_asc">Effective price ↑</option>
          <option value="price_desc">Effective price ↓</option>
        </select>
      </div>
      <div className="fb-count" aria-live="polite">
        {count} results
      </div>
    </div>
  );
}
