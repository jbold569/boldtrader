---
name: hunting-a-product
description: Hunt a specific product on the marketplaces with a Bargain Search — create it, watch fan-out and enrichment land, then read the deals it surfaces.
---

# Hunting a product

A **Bargain Search** is durable buying intent: the product you want, plus the
keyword queries an agent fans out across the marketplaces. The broad net goes
out first; precise judgment happens *after* Enrichment, never before. Read
`GLOSSARY.md` before your first hunt — the vocabulary below is not decoration,
it is what the fields mean.

## When to use

The user wants to buy a thing — "watch for HP Z440 workstations under $300",
"I need DDR4 ECC 16GB sticks" — and expects BoldTrader to keep finding it.
Also use this skill when a hunt goes thin and the net needs widening.

For fixing wrong data you find mid-hunt, switch to `correcting-data`. For
making the deal bar stricter or looser, see `tuning-thresholds`. For running
the recurring morning pass, see `daily-sweep`.

## Tools

| Tool | What it does here |
|---|---|
| `create_search` | Persist a draft Bargain Search and kick fan-out |
| `get_search` | Read one search's `status` and `match_count` |
| `search_results` | The paginated result cards, with deal math |
| `marketplace_search` | Ad-hoc query, no search context |
| `update_search` | Change the draft; bumps `version`, re-kicks fan-out |
| `delete_search` | Remove a hunt. Irreversible |

## Draft shape

`create_search` requires `summary`, `product_identity`, `queries`. Optional:
`exclusions`, `target_price`, `location` (defaults to `Kenmore, WA`).

```json
{
  "summary": "HP Z440 workstations under $300",
  "product_identity": "HP Z440 workstation, Xeon E5-1650 v2 / 16GB / 512GB SSD",
  "queries": ["hp z440", "z440 workstation", "z440 tiny"],
  "exclusions": ["no monitor"],
  "target_price": 300.0,
  "location": "Kenmore, WA"
}
```

`product_identity` is **prose**, not a model number. Per ADR 0012 the
description is what Sifting and Enrichment judge against, and it gets
rewritten later from evidence. Write the sentence you would hand a person at
the auction block: make, model, the config that matters.

A query that repeats an exclusion is a contradiction and the whole draft is
rejected `422 / invalid_draft`. So is a non-empty `queries` list of
non-strings, or a `target_price` that is not a positive number.

## Example sequence

1. `create_search` with the draft above. Response is the search resource with
   its `id`. Fan-out runs in the background — the call returns before any
   listing arrives.
2. `get_search(id=3)` until `status` is `complete`. The flow is
   `active` → `running` (fan-out in progress) → `enriching` (fan-out done,
   Enrichment pending) → `complete` (queue drained). A few seconds between
   polls is plenty; a large fan-out takes minutes.
3. `search_results(search_id=3, sort="price_asc", max_price=300)` to read
   the hits. Default filters are `verdict=match,unsure` — that is deliberate:
   an **Unidentified listing** often hides the best deal precisely because it
   is badly described, so never filter to `match` alone.
4. Read each card's `effective_price` against `fair_price` and `margin_pct`.
   A card with `fair_price: null` is cold start: fewer than 5 price
   observations for that (Product Identity, Condition) in the trailing 90
   days. There is nothing to judge it against yet — say so rather than
   guessing.
5. Reject what is wrong as you go (see `correcting-data`), and `run_search`
   again after any identity description changes so the verdicts re-sift.

## Reading the cards

- `effective_price` = out-the-door price minus the **flip value** of the
  unwanted bundled extras. `max_price` filters *this* number, never the ask.
- `fair_price` = median of the trailing 90-day **price observations** for
  that identity *and* condition. Condition changes it; the product alone
  never decides it.
- `margin_pct` = `(fair − effective) / fair × 100`.
- `verdict_stale: true` means the verdict was judged against a description
  that has since been rewritten. Re-run the search to clear it.
- `enrichment.status` is `pending`, `enriched`, or `failed`. Failed rows are
  recoverable with `reenrich_search`.

## Widening a thin hunt

Zero or few matches usually means the net is too narrow, not that the market
is empty. Add **Grandma search** queries — plain layperson terms ("cpu
tower", "gaming pc office", "dell desktop") — via `update_search`. Those are
the queries that reach sellers who do not know what they have, which is where
the good deals live.
