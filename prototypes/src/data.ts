// Fake data for the Bargain Search results look-and-feel prototype (#34).
// snake_case mirrors the JSON API contract; all numbers hand-computed to look real.

export type Verdict = "match" | "not_match" | "unsure";
export type Condition =
  | "complete"
  | "cosmetic damage"
  | "missing parts"
  | "for parts"
  | "refurbished";

export interface Enrichment {
  product: string;
  condition: Condition;
  bundle: string[];
  confidence: number; // 0..1
}

export interface ResultListing {
  id: string;
  title: string;
  url: string;
  marketplace: "eBay" | "Facebook" | "OfferUp";
  image_url: string | null;
  asking_price: number;
  shipping: number;
  out_the_door: number;
  verdict: Verdict | null; // null = sifting still pending
  enrichment: Enrichment | null; // null = enrichment failed / not recorded
  fair_price: number | null;
  flip_value: number;
  effective_price: number;
  availability: "live" | "dead";
  posted_minutes: number;
}

export const SEARCH = {
  id: "s-042",
  summary: "MacBook Air M1 13-inch, complete, under $600",
  live: { sifted: 47, total: 120, new_deals: 2 },
};

export const LISTINGS: ResultListing[] = [
  {
    id: "l-001",
    title: "MacBook Air 2020 M1 8GB 256GB Space Gray - Battery 91% Cycle 84",
    url: "https://ebay.example/itm/3847291045",
    marketplace: "eBay",
    image_url: null,
    asking_price: 459.99,
    shipping: 0,
    out_the_door: 459.99,
    verdict: "match",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 8/256)",
      condition: "complete",
      bundle: ["30W USB-C charger"],
      confidence: 0.95,
    },
    fair_price: 610,
    flip_value: 0,
    effective_price: 459.99,
    availability: "live",
    posted_minutes: 120,
  },
  {
    id: "l-002",
    title: "Apple MacBook Air M1 + Magic Keyboard + Studio Display bundle",
    url: "https://facebook.example/marketplace/1001",
    marketplace: "Facebook",
    image_url: null,
    asking_price: 1450,
    shipping: 0,
    out_the_door: 1450,
    verdict: "not_match",
    enrichment: {
      product: "Bundle: Studio Display centerpiece",
      condition: "complete",
      bundle: ["Studio Display 27\"", "Magic Keyboard", "Magic Mouse"],
      confidence: 0.88,
    },
    fair_price: null,
    flip_value: 940,
    effective_price: 510,
    availability: "live",
    posted_minutes: 300,
  },
  {
    id: "l-003",
    title: "MacBook Air 13 2020 8GB 256GB - screen crack, works perfect",
    url: "https://offerup.example/listing/7788",
    marketplace: "OfferUp",
    image_url: null,
    asking_price: 220,
    shipping: 0,
    out_the_door: 220,
    verdict: "match",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 8/256)",
      condition: "cosmetic damage",
      bundle: [],
      confidence: 0.72,
    },
    fair_price: 380,
    flip_value: 0,
    effective_price: 220,
    availability: "dead",
    posted_minutes: 1440,
  },
  {
    id: "l-004",
    title: "MacBook Air 2020 m1 BUT charger and bottom case missing",
    url: "https://ebay.example/itm/2938471234",
    marketplace: "eBay",
    image_url: null,
    asking_price: 310,
    shipping: 14.5,
    out_the_door: 324.5,
    verdict: "unsure",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 8/256)",
      condition: "missing parts",
      bundle: ["original box"],
      confidence: 0.55,
    },
    fair_price: 430,
    flip_value: 0,
    effective_price: 324.5,
    availability: "live",
    posted_minutes: 180,
  },
  {
    id: "l-005",
    title: "MacBook Air 13-inch 2017 i5 8GB - LOGIC BOARD DEAD FOR PARTS",
    url: "https://ebay.example/itm/1111999222",
    marketplace: "eBay",
    image_url: null,
    asking_price: 85,
    shipping: 22,
    out_the_door: 107,
    verdict: "not_match",
    enrichment: {
      product: "MacBook Air 13\" (2017 i5) — not M1",
      condition: "for parts",
      bundle: [],
      confidence: 0.9,
    },
    fair_price: null,
    flip_value: 120,
    effective_price: -13,
    availability: "dead",
    posted_minutes: 8640,
  },
  {
    id: "l-006",
    title: "Refurbished MacBook Air M1 8/256 1-year warranty seller direct",
    url: "https://ebay.example/itm/55551111",
    marketplace: "eBay",
    image_url: null,
    asking_price: 549,
    shipping: 0,
    out_the_door: 549,
    verdict: "match",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 8/256)",
      condition: "refurbished",
      bundle: ["charger", "keyboard cover"],
      confidence: 0.93,
    },
    fair_price: 665,
    flip_value: 0,
    effective_price: 549,
    availability: "live",
    posted_minutes: 1080,
  },
  {
    id: "l-007",
    title: "MacBook Air M1 16GB 512GB Gold - mint, AppleCare+ until 2027",
    url: "https://facebook.example/marketplace/2002",
    marketplace: "Facebook",
    image_url: null,
    asking_price: 725,
    shipping: 0,
    out_the_door: 725,
    verdict: "match",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 16/512)",
      condition: "complete",
      bundle: ["charger", "sleeve"],
      confidence: 0.81,
    },
    fair_price: 690,
    flip_value: 0,
    effective_price: 725,
    availability: "live",
    posted_minutes: 240,
  },
  {
    id: "l-008",
    title: "macbook 13\" 2020 keyboard sticking, very cheap, local pickup",
    url: "https://offerup.example/listing/9911",
    marketplace: "OfferUp",
    image_url: "",
    asking_price: 180,
    shipping: 0,
    out_the_door: 180,
    verdict: "unsure",
    enrichment: null,
    fair_price: 610,
    flip_value: 0,
    effective_price: 180,
    availability: "live",
    posted_minutes: 30,
  },
  {
    id: "l-009",
    title: "HP Chromebook 14 - student laptop, charged, slow",
    url: "https://offerup.example/listing/4433",
    marketplace: "OfferUp",
    image_url: null,
    asking_price: 60,
    shipping: 0,
    out_the_door: 60,
    verdict: "not_match",
    enrichment: {
      product: "HP Chromebook 14 (not MacBook)",
      condition: "complete",
      bundle: ["charger"],
      confidence: 0.97,
    },
    fair_price: null,
    flip_value: 0,
    effective_price: 60,
    availability: "dead",
    posted_minutes: 2880,
  },
  {
    id: "l-010",
    title: "MacBook Air M1 2020 + Synology DS220j NAS bundle price",
    url: "https://ebay.example/itm/77778888",
    marketplace: "eBay",
    image_url: null,
    asking_price: 780,
    shipping: 28,
    out_the_door: 808,
    verdict: "unsure",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 8/256)",
      condition: "complete",
      bundle: ["Synology DS220j NAS", "2TB HDD"],
      confidence: 0.64,
    },
    fair_price: 610,
    flip_value: 210,
    effective_price: 598,
    availability: "live",
    posted_minutes: 480,
  },
  {
    id: "l-011",
    title: "Macbook Air M2 2022 8/256 Midnight - like new, receipt included",
    url: "https://facebook.example/marketplace/3003",
    marketplace: "Facebook",
    image_url: null,
    asking_price: 799,
    shipping: 0,
    out_the_door: 799,
    verdict: "not_match",
    enrichment: {
      product: "MacBook Air M2 13\" (2022) — wrong model",
      condition: "complete",
      bundle: ["charger"],
      confidence: 0.91,
    },
    fair_price: null,
    flip_value: 0,
    effective_price: 799,
    availability: "dead",
    posted_minutes: 1440,
  },
  {
    id: "l-012",
    title: "MacBook Air M1 trackpad dead, screen perfect, parts or repair",
    url: "https://ebay.example/itm/66665555",
    marketplace: "eBay",
    image_url: "",
    asking_price: 150,
    shipping: 12,
    out_the_door: 162,
    verdict: "match",
    enrichment: {
      product: "MacBook Air M1 13\" (2020, 8/256)",
      condition: "for parts",
      bundle: [],
      confidence: 0.44,
    },
    fair_price: 300,
    flip_value: 180,
    effective_price: -18,
    availability: "live",
    posted_minutes: 45,
  },
  {
    id: "l-013",
    title: "Dell OptiPlex 7080 i7-10700 16GB 512GB SSD Tiny",
    url: "https://ebay.example/itm/12121212",
    marketplace: "eBay",
    image_url: null,
    asking_price: 245,
    shipping: 25,
    out_the_door: 270,
    verdict: null,
    enrichment: null,
    fair_price: null,
    flip_value: 0,
    effective_price: 270,
    availability: "live",
    posted_minutes: 0,
  },
];

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export const pct = (effective: number, fair: number) =>
  Math.round((1 - effective / fair) * 100);

export function postedLabel(minutes: number): string {
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / 1440)}d ago`;
}
