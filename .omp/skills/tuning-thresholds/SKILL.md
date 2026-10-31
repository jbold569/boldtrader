---
name: tuning-thresholds
description: Set the deal bar — global deal threshold and per-product overrides, what noise does to it, and how to tell a bad threshold from a bad market.
---

# Tuning thresholds

The **deal threshold** is how far below **fair price** a listing must fall to
count as a deal, as a percentage. At `35.0` the effective price must come in
under 65% of fair — strictly under, a listing sitting exactly on the line is
not a deal. It is the single knob that decides how loud the app is, and it is
where most of the frustration with a deal tool actually lives.

## When to use

The user says the alerts are too noisy or too quiet, a product keeps getting
called a deal at a price that is not one, or a product never fires even when
it clearly should. Also use it before judging any brand-new product: the
default is a guess about the average product, not about theirs.

## Tools

| Tool | What it does here |
|---|---|
| `get_settings` | Read the global `deal_threshold` |
| `update_settings` | Change the global `deal_threshold` |
| `get_identity` | Read one Product Identity: its description, its override |
| `list_identities` | Browse every identity and whether it overrides |
| `patch_identity` | Set or clear one product's `deal_threshold` |
| `search_results` | Read the per-card margins against the threshold |

## The precedence chain

For any listing, the effective threshold is decided in this order:

1. The Product Identity's own `deal_threshold`, if it is not `null`.
2. Otherwise the global `deal_threshold` from `get_settings` (default 25.0).
3. Then **volatility refinement** may raise it: with 30 or more trailing
   observations, the measured noise of that product's price pool is compared
   against the floor, and if noise exceeds it, the threshold rises to the
   noise floor.

Point 3 matters: a noisy product gets a higher bar automatically, so a
threshold you hand-set is a floor, not a ceiling. The refinement never
lowers your floor below what you set — it only pushes it up.

## Choosing a number

Ask what margin the user needs on resale after fees, shipping, refurbish
labor and time. That number is the floor. A 25% default is a plausible
starting point for someone reselling with real overhead, and a poor one for a
buyer who just wants one cheap thing.

- Too noisy → raise the global threshold, one notch at a time, in 5-point
  steps. A threshold raised because of volume is a preference.
- Never fire → the threshold may be fine and the data may not be. A product
  with no **fair price** (fewer than 5 trailing price observations) can
  never be a deal, at any threshold. Check `n_observations` on a card from
  that product before touching the number.
- Fires at absurd prices → this is usually a **bad identity description**
  pooling two different products into one price pool, not a bad threshold.
  Read the pool with `search_results` before changing anything. Fixing the
  identity is the fix; see `correcting-data`.

## Per-product override

```
patch_identity(identity_id=3, deal_threshold=40.0)     # set an override
patch_identity(identity_id=3, deal_threshold=null)     # clear it, fall back to global
```

`deal_threshold` must be a positive number or `null`. A hand-edit here is
not a synthesis: `synthesized_at` is untouched, and the existing verdicts
over that identity do not change until the search re-runs (`run_search`).

Overrides are for genuinely different economics — "for parts" pools, a
product with high refurbish cost, a category with a big spread. Setting an
override on everything is the same as having no per-product layer at all.

## Verifying

`list_identities` shows which identities override and which inherit.
`search_results` gives `margin_pct` per card, so you can read a product's
actual distribution instead of imagining it: how many listings clear 20%,
how many clear 35%, whether the shape says "noisy" or "thin".
`get_settings` confirms the global value you just wrote.

## Example sequence

The user says "everything you call a deal is not a deal."

1. `get_settings()` — read where the bar currently sits.
2. `search_results(search_id=3, verdict="all")` — look at the actual
   `margin_pct` numbers the complaint is about. If the "deals" cluster at 5%
   margin and the current threshold is 25, something is off in the data, not
   the knob: the computed margin contradicts the stored threshold, so read a
   card's `fair_price` and `n_observations` before going further.
3. `list_identities()` — find the identity behind those cards and check
   whether it carries a `deal_threshold` override nobody remembers setting.
4. Fix the cause: `patch_identity(identity_id=3, deal_threshold=null)` to
   drop a stale override, or `update_settings(deal_threshold=35)` to raise
   the global bar.
5. `run_search(search_id=3)` — existing verdicts were computed under the old
   number; only a re-run recomputes them.
6. `list_deals(max_price=300)` — confirm the feed now matches what the user
   considers a deal. If not, move one notch and repeat; two or three passes
   converge. Chasing the perfect number in one go is how people end up with a
   threshold of 70 and a dead app.
