// Throwaway mock backend for #22 (enhanced-view interaction prototype).
// The user's ruling: "we don't depend on production changes" — the server side is
// FAKE. This module fabricates exactly what the contract promises:
//   - GET /searches/{id}/results with server-side verdict/max_price/availability/
//     sort + the pagination envelope
//   - a POST-style mutation for per-search actions (reject, reenrichment)
//   - a long-lived event stream (enrichment / liveness / search_complete) that
//     keeps arriving while the user interacts
//   - injectable latency, error rate, and event cadence so the client's debounce,
//     stale-data, and error-handling behavior can be FELT, not imagined.
//
// The pure half (filterResults, computeSort, pickNextEvent) could lift into the
// real Python as reference behavior; nothing here touches the DOM.

import type { ResultListing } from "./data";
import { LISTINGS } from "./data";
import type { Filters, SortKey, Availability } from "./filters";

// ---------------------------------------------------------------- types ----

export interface ResultsQuery {
  page: number;
  per_page: number;
  verdicts: string[]; // subset of match|unsure|not_match; empty = none
  max_price: number | null;
  availability: Availability | "all";
  sort: SortKey;
}

export interface Envelope<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export type BgEvent =
  | { event: "enrichment"; data: { listing_id: string; status: "enriched" | "failed" } }
  | { event: "liveness"; data: { search_id: number; done: boolean; dead_count: number; banner: string } }
  | { event: "search_complete"; data: { search_id: number; match_count: number } };

// ------------------------------------------------------------ fixtures ----

// The real corpus for the interaction prototype: #34's 15 listings plus a pool
// of "inbound" listings the background stream delivers during the session.
let POOL: ResultListing[] = LISTINGS.map((r) => ({ ...r }));
const INBOUND: ResultListing[] = [
  ["mac-201", "MacBook Air 13 M2 256GB Space Gray", 520, 15, "eBay", "match", 640],
  ["mac-202", "MacBook Air M1 8/256 + dock and bag", 430, 0, "OfferUp", "match", 610],
  ["mac-203", "Apple MacBook Air 13\" 2020 i5 16GB", 690, 25, "Facebook", "unsure", 700],
  ["fb-211", "MacBook Air M2 13-inch complete boxed", 585, 0, "Facebook", "match", 650],
  ["fb-212", "MacBook Air 13 dead screen for parts", 90, 0, "Facebook", "not_match", 0],
  ["eu-221", "MacBook Air A2337 512GB with charger", 615, 40, "eBay", "match", 720],
]
  .map((row, i) => {
    const [id, title, asking, ship, marketplace, verdict, fair] = row as [
      string, string, number, number, "eBay" | "Facebook" | "OfferUp", "match" | "unsure" | "not_match", number
    ];
    return {
      id,
      title,
      url: `https://example.invalid/${id}`,
      marketplace,
      image_url: null,
      asking_price: asking,
      shipping: ship,
      out_the_door: asking + ship,
      verdict: verdict as ResultListing["verdict"],
      enrichment: null,
      fair_price: fair || null,
      flip_value: asking * 1.25,
      effective_price: asking + ship,
      availability: "live" as const,
      posted_minutes: 2,
    };
  });

// Mutable server-side store. Events mutate it; queries read it.
let STORE: ResultListing[] = [...POOL];
let SIFTED = 47;

// ---------------------------------------------------------------- config --

export interface MockSettings {
  latencyMs: number; // server response time
  errorRate: number; // 0..1 chance of a 500 on any query
  eventEveryMs: number; // background event cadence; 0 = silent
}

export const SETTINGS: MockSettings = {
  latencyMs: 90,
  errorRate: 0,
  eventEveryMs: 4000,
};

// --------------------------------------------------------- pure queries ---

export function filterResults(store: ResultListing[], q: ResultsQuery): ResultListing[] {
  const allVerdicts = ["match", "unsure", "not_match"].every((v) => q.verdicts.includes(v));
  const f = filtered(store, q, allVerdicts);
  return sorted(f, q.sort);
}

function filtered(store: ResultListing[], q: ResultsQuery, allVerdicts: boolean) {
  return store.filter((r) => {
    if (r.verdict === null) {
      if (!allVerdicts) return false;
    } else if (!q.verdicts.includes(r.verdict)) return false;
    if (q.max_price !== null && r.effective_price > q.max_price) return false;
    if (q.availability !== "all" && r.availability !== q.availability) return false;
    return true;
  });
}

function sorted(rows: ResultListing[], sort: SortKey): ResultListing[] {
  const out = [...rows];
  if (sort === "price_asc") out.sort((a, b) => a.effective_price - b.effective_price);
  if (sort === "price_desc") out.sort((a, b) => b.effective_price - a.effective_price);
  // newest: posted_minutes ascending (fresh first); equal minutes keep insertion
  if (sort === "newest") out.sort((a, b) => a.posted_minutes - b.posted_minutes);
  return out;
}
function delay<T>(v: T): Promise<T> {
  const { promise, resolve } = Promise.withResolvers<T>();
  setTimeout(resolve, SETTINGS.latencyMs, v);
  return promise;
}

function boom(msg: string): Promise<never> {
  const { promise, reject } = Promise.withResolvers<never>();
  setTimeout(reject, SETTINGS.latencyMs, { code: "server_error", message: msg });
  return promise;
}

export interface ResultsMeta {
  total: number;
  sifted: number;
  of: number;
}

export function getResults(q: ResultsQuery): Promise<{ env: Envelope<ResultListing>; meta: ResultsMeta }> {
  if (Math.random() < SETTINGS.errorRate) return boom("Simulated backend failure (mock)");
  const rows = filterResults(STORE, q);
  const start = (q.page - 1) * q.per_page;
  const env: Envelope<ResultListing> = {
    items: rows.slice(start, start + q.per_page),
    page: q.page,
    per_page: q.per_page,
    total: rows.length,
    total_pages: Math.max(1, Math.ceil(rows.length / q.per_page)),
  };
  return delay({ env, meta: { total: rows.length, sifted: SIFTED, of: STORE.length } });
}

export function rejectListing(listingId: string, reason: string): Promise<{ ok: true }> {
  STORE = STORE.map((r) => (r.id === listingId ? { ...r, availability: "dead" as const } : r));
  return delay({ ok: true } as const);
}

export function reenrich(): Promise<{ requeued: number }> {
  const n = STORE.filter((r) => r.enrichment === null).length;
  STORE = STORE.map((r) =>
    r.enrichment === null
      ? { ...r, enrichment: { product: r.title.slice(0, 24), condition: "complete" as const, bundle: [], confidence: 0.82 } }
      : r
  );
  return delay({ requeued: n });
}

// ---------------------------------------------------- event generator ----
// A scripted, repeating background script so demos are predictable.
// Each tick advances the world: a new listing arrives, enrichment lands on a
// pending one, liveness dies one, or the search completes.

let tick = 0;
let inboundIdx = 0;
let deadCount = 0;

export function nextEvent(): BgEvent {
  const step = tick % 4;
  tick++;
  if (step === 0 && inboundIdx < INBOUND.length) {
    const item = { ...INBOUND[inboundIdx++] };
    STORE = [item, ...STORE];
    SIFTED += 1;
    return { event: "search_complete", data: { search_id: 42, match_count: STORE.filter((r) => r.verdict === "match").length } };
  }
  if (step === 1) {
    const target = STORE[Math.floor(Math.random() * STORE.length)];
    if (target)
      STORE = STORE.map((r) =>
        r.id === target.id
          ? { ...r, enrichment: { product: r.title.slice(0, 24), condition: "complete" as const, bundle: ["charger"], confidence: 0.9 } }
          : r
      );
    return { event: "enrichment", data: { listing_id: target?.id ?? "?", status: "enriched" } };
  }
  if (step === 2) {
    const live = STORE.filter((r) => r.availability === "live");
    const victim = live[Math.floor(Math.random() * live.length)];
    if (victim) {
      STORE = STORE.map((r) => (r.id === victim.id ? { ...r, availability: "dead" as const } : r));
      deadCount++;
    }
    return { event: "liveness", data: { search_id: 42, done: deadCount >= 6, dead_count: deadCount, banner: deadCount >= 3 ? `${deadCount} listings ended since the last check` : "" } };
  }
  // step 3: a fresh inbound with its own verdict
  if (inboundIdx < INBOUND.length) {
    const item = { ...INBOUND[inboundIdx++] };
    STORE = [item, ...STORE];
    SIFTED += 1;
    return { event: "search_complete", data: { search_id: 42, match_count: STORE.filter((r) => r.verdict === "match").length } };
  }
  return { event: "liveness", data: { search_id: 42, done: true, dead_count: deadCount, banner: "" } };
}

// Re-seed for scenario resets.
export function resetWorld(seed?: ResultListing[]) {
  STORE = (seed ?? LISTINGS).map((r) => ({ ...r }));
  POOL = STORE;
  SIFTED = 47;
  tick = 0;
  inboundIdx = 0;
  deadCount = 0;
}

export function currentStore(): ResultListing[] {
  return STORE;
}
