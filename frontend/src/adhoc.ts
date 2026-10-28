// Ad-hoc Marketplace Search params (ticket #48). A deliberately separate,
// small param set from `Filters` (#46): the ad-hoc page asks a live
// Marketplace for one page of raw Listings — nothing to sort, nothing to
// filter by verdict — so giving it the Filters shape would be a lie about
// what the query does (docs/frontend-architecture.md "State strategy":
// `/search` params are `q`, `marketplace`, `location`, `page`).
// URL <-> value conversion and the submit-time validation live here so both
// are testable without a browser.

export const MARKETPLACE_OPTIONS = [
  { value: "all", label: "All marketplaces" },
  { value: "offerup", label: "OfferUp" },
  { value: "facebook", label: "Facebook" },
];

// Local marketplaces are metro-scoped: without a location they see nothing
// useful (GLOSSARY: Locality).
const LOCAL: Record<string, true> = { offerup: true, facebook: true };

/** The three fields the user fills in. */
export interface AdhocForm {
  q: string;
  marketplace: string;
  location: string;
}

/** What the URL carries: the form plus the page pointer. */
export interface AdhocQuery extends AdhocForm {
  page: number;
}

function toParams(
  query: string | URLSearchParams | null | undefined,
): URLSearchParams {
  if (query instanceof URLSearchParams) return query;
  return new URLSearchParams(query ?? "");
}

/**
 * URL query string -> AdhocQuery. Absent params fall back to the defaults
 * and garbage is ignored rather than thrown: a stale bookmark must never
 * break the page (same rule as parseFilters).
 */
export function parseAdhoc(
  query: string | URLSearchParams | null | undefined,
): AdhocQuery {
  const params = toParams(query);

  const value = (params.get("marketplace") || "all").trim().toLowerCase();
  const marketplace = MARKETPLACE_OPTIONS.some((o) => o.value === value)
    ? value
    : "all";

  let page = 1;
  const raw = params.get("page");
  if (raw !== null && raw.trim() !== "") {
    const n = Number(raw);
    if (Number.isInteger(n) && n >= 1) page = n;
  }

  return {
    q: (params.get("q") ?? "").trim(),
    marketplace,
    location: params.get("location") ?? "",
    page,
  };
}

/**
 * Submit-time validation only (#48): the whole form is checked once, on
 * submit — typing never re-queries, so there is nothing to validate
 * per-keystroke.
 */
export function validateAdhoc(form: AdhocForm): Record<string, string> {
  const errs: Record<string, string> = {};
  if (!form.q.trim()) errs.q = "Type what you're after.";
  else if (form.q.trim().length < 2) errs.q = "At least two characters.";
  if (LOCAL[form.marketplace] && !form.location.trim())
    errs.location = "Required for local marketplaces.";
  return errs;
}
