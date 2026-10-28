// Ad-hoc Search param tests (ticket #48). Same discipline as filters.test.ts:
// the URL is the query key, so URL -> value parsing and the submit-time
// validation are the contract under test — pure functions, no browser.

import { describe, it, expect } from "vitest";
import { MARKETPLACE_OPTIONS, parseAdhoc, validateAdhoc } from "./adhoc";

describe("parseAdhoc", () => {
  it("falls back to the defaults for empty / absent input", () => {
    for (const q of ["", "?", null, undefined]) {
      expect(parseAdhoc(q)).toEqual({
        q: "",
        marketplace: "all",
        location: "",
        page: 1,
      });
    }
  });

  it("parses the full set", () => {
    expect(
      parseAdhoc("?q=hp%20z440&marketplace=offerup&location=Kenmore%2C%20WA&page=3"),
    ).toEqual({
      q: "hp z440",
      marketplace: "offerup",
      location: "Kenmore, WA",
      page: 3,
    });
  });

  it("drops an unknown marketplace back to all", () => {
    expect(parseAdhoc("marketplace=craigslist").marketplace).toBe("all");
  });

  it("ignores malformed page instead of throwing", () => {
    expect(parseAdhoc("page=0").page).toBe(1);
    expect(parseAdhoc("page=1.5").page).toBe(1);
    expect(parseAdhoc("page=-2").page).toBe(1);
    expect(parseAdhoc("page=soon").page).toBe(1);
    expect(parseAdhoc("page=").page).toBe(1);
  });

  it("accepts URLSearchParams directly", () => {
    const p = new URLSearchParams("q=drum&marketplace=facebook&page=2");
    expect(parseAdhoc(p)).toEqual({
      q: "drum",
      marketplace: "facebook",
      location: "",
      page: 2,
    });
  });

  it("round-trips through patchSearch", () => {
    const url =
      "q=guitar&marketplace=offerup&location=Tacoma%2C%20WA&page=4";
    const parsed = parseAdhoc(url);
    const rebuilt = new URLSearchParams({
      q: parsed.q,
      marketplace: parsed.marketplace,
      location: parsed.location,
      page: String(parsed.page),
    }).toString();
    expect(parseAdhoc(rebuilt)).toEqual(parsed);
  });
});

describe("validateAdhoc", () => {
  it("requires a query", () => {
    expect(validateAdhoc({ q: "", marketplace: "all", location: "" })).toHaveProperty("q");
    expect(validateAdhoc({ q: "   ", marketplace: "all", location: "" })).toHaveProperty("q");
  });

  it("requires at least two characters", () => {
    expect(validateAdhoc({ q: "a", marketplace: "all", location: "" })).toHaveProperty("q");
    expect(validateAdhoc({ q: "ab", marketplace: "all", location: "" })).toEqual({});
  });

  it("requires a location on local marketplaces only", () => {
    expect(validateAdhoc({ q: "desk", marketplace: "offerup", location: "" })).toHaveProperty("location");
    expect(validateAdhoc({ q: "desk", marketplace: "facebook", location: "" })).toHaveProperty("location");
    expect(validateAdhoc({ q: "desk", marketplace: "all", location: "" })).toEqual({});
  });

  it("reports every problem at once", () => {
    const errs = validateAdhoc({ q: "", marketplace: "offerup", location: "  " });
    expect(Object.keys(errs).sort()).toEqual(["location", "q"]);
  });

  it("every option except the local ones needs no location", () => {
    for (const o of MARKETPLACE_OPTIONS) {
      const local = o.value === "offerup" || o.value === "facebook";
      const errs = validateAdhoc({ q: "desk", marketplace: o.value, location: "" });
      expect("location" in errs).toBe(local);
    }
  });
});
