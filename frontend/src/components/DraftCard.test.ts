// Draft-card pure helpers (ticket #50). The card itself is visual; what
// must be locked down is the identity contract: save/discard dispositions
// are keyed by draft content, and target_price crosses the number↔string
// boundary without leaking null into the form.

import { describe, it, expect } from "vitest";
import { draftKey, draftToForm } from "./DraftCard";
import type { Draft } from "../api/types";

const d: Draft = {
  summary: "s",
  product_identity: "p",
  queries: ["a"],
  exclusions: [],
  target_price: 300,
  location: "Kenmore, WA",
};

describe("draftKey", () => {
  it("equal drafts get equal keys regardless of object identity", () => {
    expect(draftKey(d)).toBe(draftKey({ ...d }));
  });
  it("different drafts get different keys", () => {
    expect(draftKey(d)).not.toBe(draftKey({ ...d, target_price: 250 }));
  });
  it("key order across fields does not matter", () => {
    const a = draftKey(d);
    const { summary, ...rest } = d;
    // Same content, different literal key order.
    expect(draftKey({ ...rest, summary } as Draft)).toBe(a);
  });
});

describe("draftToForm", () => {
  it("null target_price becomes the empty string the form expects", () => {
    expect(draftToForm({ ...d, target_price: null }).target_price).toBe("");
  });
  it("numeric target_price becomes its string form", () => {
    expect(draftToForm(d).target_price).toBe("300");
  });
  it("passes the other six fields through", () => {
    const f = draftToForm(d);
    expect(f.summary).toBe("s");
    expect(f.queries).toEqual(["a"]);
    expect(f.exclusions).toEqual([]);
  });
});
