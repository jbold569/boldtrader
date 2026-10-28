// Pure filter-param <-> URL module (ticket #46). The URL query string IS the
// query key (docs/frontend-architecture.md "State strategy"): these functions
// are the unit under test — no React, no network, no side effects.
//
// Asymmetry worth knowing (docs/api-contract.md results table): on the wire an
// ABSENT `verdict` means the contract default `match,unsure`. So default
// omission is not symmetric for verdict: an explicit `verdict=match,unsure`
// is an override ("everything except not_match"), NOT the default. The
// URL shorthand `all` / `none` exist precisely to name the states the joined
// list cannot.
//
// `none` is a client-visible state (show nothing). The backend 400s an
// unknown `none` verdict, so callers must not issue a results query while
// the selection is empty (see the page's `enabled` guard). Parsing still
// round-trips it faithfully.

export type Verdict = "match" | "unsure" | "not_match";
export type Availability = "all" | "live" | "dead";
export type SortKey = "newest" | "price_asc" | "price_desc";

// Display density (#47). Client-only: it selects which renderer paints the
// same results, never a backend filter (see buildQuery).
export type Density = "tile" | "condensed";

export const VERDICT_KEYS: Verdict[] = ["match", "unsure", "not_match"];

export const VERDICT_LABELS: Record<Verdict, string> = {
  match: "Match",
  unsure: "Unsure",
  not_match: "Not a match",
};

// The contract default result view: match + unsure, not_match hidden.
export const DEFAULT_VERDICTS: Record<Verdict, boolean> = {
  match: true,
  unsure: true,
  not_match: false,
};

export const DEFAULT_WIRE_VERDICT = "match,unsure";

export interface Filters {
  verdicts: Record<Verdict, boolean>;
  max_price: number | null;
  availability: Availability;
  sort: SortKey;
  page: number;
}

export const DEFAULT_FILTERS: Filters = {
  verdicts: { ...DEFAULT_VERDICTS },
  max_price: null,
  availability: "all",
  sort: "newest",
  page: 1,
};

function isVerdict(s: string): s is Verdict {
  return (VERDICT_KEYS as string[]).includes(s);
}

/** Coerce the loose inputs (raw "?a=b", raw "a=b", URLSearchParams) to params. */
function toParams(
  query: string | URLSearchParams | null | undefined,
): URLSearchParams {
  if (query instanceof URLSearchParams) return new URLSearchParams(query);
  if (typeof query !== "string") return new URLSearchParams();
  return new URLSearchParams(query.replace(/^\?/, ""));
}

/**
 * URL query string -> Filters. Absent params fall back to the defaults;
 * malformed values are ignored (default kept) rather than throwing: a stale
 * bookmark must never break the page.
 */
export function parseFilters(
  query: string | URLSearchParams | null | undefined,
): Filters {
  const params = toParams(query);

  const f: Filters = {
    verdicts: { ...DEFAULT_VERDICTS },
    max_price: null,
    availability: "all",
    sort: "newest",
    page: 1,
  };

  const v = params.get("verdict");
  if (v === "all") {
    f.verdicts = { match: true, unsure: true, not_match: true };
  } else if (v === "none") {
    f.verdicts = { match: false, unsure: false, not_match: false };
  } else if (v !== null) {
    const picked = v
      .split(",")
      .map((s) => s.trim())
      .filter(isVerdict);
    if (picked.length > 0) {
      f.verdicts = { match: false, unsure: false, not_match: false };
      for (const k of picked) f.verdicts[k] = true;
    }
  }

  const mp = params.get("max_price");
  if (mp !== null && mp.trim() !== "") {
    const n = Number(mp);
    if (Number.isFinite(n) && n >= 0) f.max_price = n;
  }

  const av = params.get("availability");
  if (av === "live" || av === "dead" || av === "all") f.availability = av;

  const st = params.get("sort");
  if (st === "newest" || st === "price_asc" || st === "price_desc")
    f.sort = st;

  const pg = params.get("page");
  if (pg !== null && pg.trim() !== "") {
    const n = Number(pg);
    if (Number.isInteger(n) && n >= 1) f.page = n;
  }

  return f;
}

/**
 * Filters -> wire params for GET /searches/{id}/results. Defaults omitted so
 * the URL (and the query key) stay clean.
 *
 * The empty verdict selection serializes as `none` so a reload keeps the
 * narrow view; the page's `enabled` guard keeps it off the wire (the backend
 * 400s an unknown `none` verdict).
 */
export function buildQuery(f: Filters): Record<string, string> {
  const q: Record<string, string> = {};

  const selected = VERDICT_KEYS.filter((k) => f.verdicts[k]);
  if (selected.length === 0) {
    q.verdict = "none";
  } else {
    const joined = selected.join(",");
    if (joined !== DEFAULT_WIRE_VERDICT) q.verdict = joined;
  }

  if (f.max_price !== null) q.max_price = String(f.max_price);
  if (f.availability !== "all") q.availability = f.availability;
  if (f.sort !== "newest") q.sort = f.sort;
  if (f.page > 1) q.page = String(f.page);

  return q;
}

/**
 * Filters -> URL query string (the query key). Defaults omitted.
 */
export function buildSearch(f: Filters): string {
  return new URLSearchParams(buildQuery(f)).toString();
}

/**
 * Patch the current URL query string: `updates` entries set a param; null /
 * undefined / empty-string deletes it. Pure — returns the new query string,
 * touches nothing.
 */
export function patchSearch(
  current: string | URLSearchParams,
  updates: Record<string, string | number | boolean | null | undefined>,
): string {
  const params = toParams(current);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === undefined || value === "") {
      params.delete(key);
    } else {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

/**
 * URL query -> display density (#47). Deliberately NOT part of `Filters`:
 * the Filters object is the wire query key for GET /results, and flipping
 * the renderer must never look like a new server query. `view=condensed`
 * is the only truth; absent or anything else is `tile` (the omitted
 * default), so toggling back just deletes the param.
 */
export function parseDensity(
  query: string | URLSearchParams | null | undefined,
): Density {
  return toParams(query).get("view") === "condensed" ? "condensed" : "tile";
}
