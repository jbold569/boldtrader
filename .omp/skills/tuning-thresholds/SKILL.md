---
name: tuning-thresholds
description: Read deal margins as a human judgment at view time — there is no stored threshold. How to read margin_pct, fair price, and cold starts when judging deals by eye.
---

# Tuning thresholds

There is no stored deal threshold. Nothing in the system decides what
counts as a deal: `margin_pct = (fair − effective) / fair × 100` is raw
material, and the buyer's judgment at the moment of looking is the
verdict. This skill is about reading those numbers well, not setting any.

## When to use

The user says the alerts are too noisy or too quiet, a product keeps
looking like a deal at a price that is not one, or a product never looks
like a deal. Also use it before judging any brand-new product: its fair
price may not exist yet, and "no data" reads exactly like "no deals."

## Tools

| Tool | What it does here |
|---|---|
| `list_deals` | The flat margin feed, sorted `margin_desc` by default |
| `search_results` | Per-card `margin_pct`, `fair_price`, `n_observations` |
| `list_identities` | Every identity with counts and per-condition fair prices |
| `get_identity` | One identity: description, listings, fair prices |

## Reading the numbers

- `margin_pct` is computed at read time from the trailing 90-day fair
  price. A positive margin is not automatically a deal: on a thin
  product a 30% margin can be two stale observations agreeing with
  themselves.
- `n_observations` is the first thing to check, not the last. Below 5
  observations in the window there is no fair price, no margin, and no
  basis for a deal claim. That is cold start, not a verdict.
- A noisy pool (wide spread between card margins) demands a bigger
  discount to mean anything. A tight pool makes a small margin
  meaningful. Read the shape across `search_results` before believing
  any single card.

## When the judgment goes wrong

- Everything looks like a deal → the fair price may be dragged down or
  the margins misread. Check `n_observations` and spread on a few
  cards before concluding anything.
- Nothing ever looks like a deal → most often there is no fair price
  yet, not a dead market. `list_identities` shows `observation_count`
  per identity; near zero means the pipeline needs days, and `run_search
  + re-enrichment` to accumulate them.
- Fires at absurd prices → usually a **bad identity description**
  pooling two different products into one price pool. Read the pool
  with `search_results`; fixing the identity is the fix — see
  `correcting-data`.

## Example sequence

The user says "everything you call a deal is not a deal."

1. `search_results(search_id=3, verdict="all")` — read the actual
   `margin_pct` numbers behind the complaint. If they cluster at 5%,
   nothing needs changing; the judgment was never stored anywhere.
2. `list_identities()` — check `observation_count` and `fair_prices`
   for the identity behind those cards. A pool mixing two products
   shows up as margins that make no sense per card.
3. `get_identity(identity_id=3)` — read the description itself; if it
   is vague, the pool is polluted. Fix the description
   (`patch_identity(description=...)`), or reject-and-correct the
   wrong listings so their reasons land in the Exclusions block.
4. `run_search(search_id=3)` — re-sift under the fixed description.
5. `list_deals(max_price=300)` — look again. Two or three passes of
   reading and correcting converge; there is no knob to over-turn.
