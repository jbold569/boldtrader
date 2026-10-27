// Shared filter/sort logic for the results views. Mirrors the contract params of
// GET /searches/{id}/results: verdict (comma list), max_price, availability,
// sort. The URL is the single source of truth; no component state.

import type { ResultListing, Verdict } from "./data";
export type { Verdict };

export type SortKey = "newest" | "price_asc" | "price_desc";
export type Availability = "all" | "live" | "dead";

export const VERDICT_KEYS: Verdict[] = ["match", "unsure", "not_match"];

export const VERDICT_LABELS: Record<Verdict, string> = {
  match: "Match",
  unsure: "Unsure",
  not_match: "Not a match",
};

export type VerdictSelection = Record<Verdict, boolean>;

export interface Filters {
  verdicts: VerdictSelection;
  maxPrice: number | null;
  availability: Availability;
  sort: SortKey;
}

export const DEFAULT_FILTERS: Filters = {
  verdicts: { match: true, unsure: true, not_match: false },
  maxPrice: null,
  availability: "all",
  sort: "newest",
};

// Parse from a URLSearchParams. Absent params fall back to contract defaults
// (verdict=match,unsure); malformed values are ignored rather than throwing.
export function parseFilters(params: URLSearchParams): Filters {
  const f: Filters = {
    verdicts: { match: true, unsure: true, not_match: false },
    maxPrice: null,
    availability: "all",
    sort: "newest",
  };

  const v = params.get("verdict");
  if (v !== null) {
    if (v === "all") {
      f.verdicts = { match: true, unsure: true, not_match: true };
    } else if (v === "none") {
      f.verdicts = { match: false, unsure: false, not_match: false };
    } else {
      const picked = v
        .split(",")
        .map((s) => s.trim())
        .filter((s): s is Verdict => VERDICT_KEYS.includes(s as Verdict));
      if (picked.length > 0) {
        f.verdicts = { match: false, unsure: false, not_match: false };
        for (const k of picked) f.verdicts[k] = true;
      }
    }
  }

  const mp = params.get("max_price");
  if (mp !== null && mp.trim() !== "") {
    const n = Number(mp);
    if (Number.isFinite(n) && n >= 0) f.maxPrice = n;
  }

  const av = params.get("availability");
  if (av === "live" || av === "dead" || av === "all") f.availability = av;

  const st = params.get("sort");
  if (st === "newest" || st === "price_asc" || st === "price_desc")
    f.sort = st;

  return f;
}

export function serializeVerdicts(sel: VerdictSelection): string {
  const selected = VERDICT_KEYS.filter((k) => sel[k]);
  if (selected.length === 0) return "none";
  if (selected.length === VERDICT_KEYS.length) return "all";
  return selected.join(",");
}

// Patch query params in place and re-render (popstate). null removes a param.
export function patchUrl(updates: Record<string, string | null>) {
  const p = new URLSearchParams(window.location.search);
  for (const [k, val] of Object.entries(updates)) {
    if (val === null) p.delete(k);
    else p.set(k, val);
  }
  const qs = p.toString();
  window.history.replaceState(null, "", qs ? `?${qs}` : "/");
  window.dispatchEvent(new PopStateEvent("popstate"));
}

// Apply filter then sort. Returns a new array; input untouched.
// max_price filters on effective price — the deal-comparison number, not the ask.
// Pending (verdict-less) listings show only when every verdict is selected.
export function applyFilters(
  listings: ResultListing[],
  f: Filters
): ResultListing[] {
  const allVerdicts = VERDICT_KEYS.every((k) => f.verdicts[k]);
  const filtered = listings.filter((r) => {
    if (r.verdict === null) {
      if (!allVerdicts) return false;
    } else if (!f.verdicts[r.verdict]) {
      return false;
    }
    if (f.maxPrice !== null && r.effective_price > f.maxPrice) return false;
    if (f.availability !== "all" && r.availability !== f.availability)
      return false;
    return true;
  });

  const sorted = [...filtered];
  if (f.sort === "price_asc")
    sorted.sort((a, b) => a.effective_price - b.effective_price);
  if (f.sort === "price_desc")
    sorted.sort((a, b) => b.effective_price - a.effective_price);
  return sorted;
}
