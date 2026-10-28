// Filter-param <-> URL sync tests (ticket #46). The URL *is* the query key,
// so these pure functions are the contract: URL -> filters -> wire query,
// default omission, and the round-trip stability that makes reload and
// back/forward land on the same view.

import { describe, it, expect } from "vitest";
import {
  DEFAULT_FILTERS,
  type Filters,
  buildQuery,
  buildSearch,
  patchSearch,
  parseFilters,
} from "./filters";

describe("parseFilters", () => {
  it("falls back to the defaults for empty / absent input", () => {
    for (const q of ["", "?", null, undefined]) {
      expect(parseFilters(q)).toEqual(DEFAULT_FILTERS);
    }
  });

  it("ignores unrelated params", () => {
    expect(parseFilters("?foo=bar&baz=1")).toEqual(DEFAULT_FILTERS);
  });

  it("parses each filter", () => {
    const f = parseFilters(
      "?verdict=not_match&max_price=50&availability=live&sort=price_asc&page=3",
    );
    expect(f).toEqual({
      verdicts: { match: false, unsure: false, not_match: true },
      max_price: 50,
      availability: "live",
      sort: "price_asc",
      page: 3,
    });
  });

  it("parses the all / none verdict shorthands", () => {
    expect(parseFilters("verdict=all").verdicts).toEqual({
      match: true,
      unsure: true,
      not_match: true,
    });
    expect(parseFilters("verdict=none").verdicts).toEqual({
      match: false,
      unsure: false,
      not_match: false,
    });
  });

  it("trims whitespace in the verdict list", () => {
    expect(parseFilters("verdict=%20match%20,%20unsure%20").verdicts).toEqual({
      match: true,
      unsure: true,
      not_match: false,
    });
  });

  it("keeps the valid tokens and drops unknown ones", () => {
    expect(parseFilters("verdict=match,zzz").verdicts).toEqual({
      match: true,
      unsure: false,
      not_match: false,
    });
  });

  it("ignores malformed values instead of throwing", () => {
    // Every one of these is garbage for its field; the default must survive.
    expect(parseFilters("max_price=abc").max_price).toBeNull();
    expect(parseFilters("max_price=-5").max_price).toBeNull();
    expect(parseFilters("page=0").page).toBe(1);
    expect(parseFilters("page=1.5").page).toBe(1);
    expect(parseFilters("page=-2").page).toBe(1);
    expect(parseFilters("page=soon").page).toBe(1);
    expect(parseFilters("availability=zzz").availability).toBe("all");
    expect(parseFilters("sort=foo").sort).toBe("newest");
    expect(parseFilters("verdict=foo").verdicts).toEqual(DEFAULT_FILTERS.verdicts);
  });

  it("accepts zero as a real max_price", () => {
    expect(parseFilters("max_price=0").max_price).toBe(0);
  });

  it("treats an empty max_price as no filter", () => {
    expect(parseFilters("max_price=").max_price).toBeNull();
  });

  it("reads a leading question mark", () => {
    expect(parseFilters("?sort=price_desc").sort).toBe("price_desc");
  });

  it("accepts URLSearchParams directly", () => {
    const p = new URLSearchParams("sort=price_asc&page=2");
    expect(parseFilters(p)).toEqual({
      ...DEFAULT_FILTERS,
      sort: "price_asc",
      page: 2,
    });
  });
});

describe("buildQuery / buildSearch", () => {
  it("omits every default", () => {
    expect(buildSearch(DEFAULT_FILTERS)).toBe("");
  });

  it("serialises non-default values", () => {
    const f: Filters = {
      verdicts: { match: true, unsure: false, not_match: true },
      max_price: 49.5,
      availability: "dead",
      sort: "price_asc",
      page: 4,
    };
    expect(buildQuery(f)).toEqual({
      verdict: "match,not_match",
      max_price: "49.5",
      availability: "dead",
      sort: "price_asc",
      page: "4",
    });
  });

  it("keeps page one out of the URL", () => {
    const f = { ...DEFAULT_FILTERS, availability: "live" as const };
    expect(buildSearch(f)).toBe("availability=live");
  });

  it("names the empty verdict selection 'none'", () => {
    const f = {
      ...DEFAULT_FILTERS,
      verdicts: { match: false, unsure: false, not_match: false },
    };
    expect(buildSearch(f)).toBe("verdict=none");
  });

  it("writes all three verdicts explicitly rather than 'all'", () => {
    // The wire list is emitted in full so the request never relies on the
    // `all` shorthand the default-omission rule would otherwise hide.
    // (URLSearchParams percent-encodes the commas; parse_qs and
    // parseFilters both decode it, so the round-trip is unaffected.)
    const f = {
      ...DEFAULT_FILTERS,
      verdicts: { match: true, unsure: true, not_match: true },
    };
    expect(buildSearch(f)).toBe("verdict=match%2Cunsure%2Cnot_match");
  });
});

describe("round-trip stability", () => {
  const urls = [
    "",
    "verdict=match",
    "verdict=all",
    "verdict=none",
    "verdict=unsure&max_price=25",
    "sort=price_desc&availability=live&page=7",
    "verdict=match,not_match&max_price=199&availability=dead&sort=price_asc&page=2",
  ];

  for (const url of urls) {
    it(`build(parse(${JSON.stringify(url)})) parses back identical`, () => {
      const once = parseFilters(url);
      const twice = parseFilters(buildSearch(once));
      expect(twice).toEqual(once);
      // And the serialised form is a fixed point too.
      expect(buildSearch(twice)).toBe(buildSearch(once));
    });
  }

  it("round-trips a re-patched URL (back/forward shape)", () => {
    // Forward: change the sort. Back: the browser hands back the older
    // entry verbatim; both must be valid, distinct views.
    const forward = patchSearch("", { sort: "price_asc" });
    const back = "";
    expect(parseFilters(forward).sort).toBe("price_asc");
    expect(parseFilters(back).sort).toBe("newest");
  });
});

describe("patchSearch", () => {
  it("sets, overwrites and deletes params", () => {
    expect(patchSearch("", { verdict: "match" })).toBe("verdict=match");
    expect(patchSearch("verdict=match", { verdict: "unsure" })).toBe(
      "verdict=unsure",
    );
    expect(patchSearch("verdict=match&page=3", { page: null })).toBe(
      "verdict=match",
    );
    expect(patchSearch("verdict=match&page=3", { page: undefined })).toBe(
      "verdict=match",
    );
    expect(patchSearch("verdict=match&page=3", { page: "" })).toBe(
      "verdict=match",
    );
  });

  it("coerces numbers", () => {
    expect(patchSearch("", { page: 5 })).toBe("page=5");
  });

  it("leaves the incoming params untouched", () => {
    const p = new URLSearchParams("sort=newest");
    patchSearch(p, { sort: "price_asc" });
    expect(p.get("sort")).toBe("newest");
  });

  it("a filter change wipes the page so the new view starts at 1", () => {
    const next = patchSearch("sort=price_desc&page=4", {
      max_price: "80",
      page: null,
    });
    const f = parseFilters(next);
    expect(f.page).toBe(1);
    expect(f.max_price).toBe(80);
    expect(f.sort).toBe("price_desc");
  });
});
