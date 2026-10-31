---
name: correcting-data
description: Fix wrong Enrichment — reject or restore listings, author descriptions for unidentifiable ones, correct product/condition/bundle, merge duplicate Product Identities.
---

# Correcting bad data

Enrichment is a first draft by a model and it is wrong often: wrong
condition, missed bundle contents, a product resolved to the wrong thing. A
**Correction** is user truth. Nothing overwrites it, ever. That makes
correcting the highest-leverage thing you can do for the whole system: every
corrected listing is a fact the pricing database can trust.

## When to use

A result card shows a condition that is wrong, a product that is not what the
listing actually is, a bundle that missed the monitor, or the same product
sitting under two different identities ("HP Z440" and "HP Z440 Workstation").

If you are creating or widening a hunt instead, see `hunting-a-product`.

## Tools

| Tool | What it does here |
|---|---|
| `correct_enrichment` | Hand-set a listing's enriched facts; freezes the listing |
| `patch_listing` | Set an authored description; re-queues Enrichment |
| `create_rejection` | Reject a card and feed its reason to the exclusion list |
| `restore_rejection` | Undo a rejection; the listing is asserted to BE the product |
| `merge_identities` | Fold a duplicate Product Identity into the winner |
| `patch_identity` | Hand-edit a description or threshold |
| `retune_identity` | Model rewrites a description from accumulated evidence |
| `reenrich_search` | Re-queue missing or failed Enrichment for one search |

## The condition set

`condition` must be one of: `complete`, `cosmetic damage`, `missing parts`,
`for parts`, `refurbished`, or `unknown`. Anything else is
`422 / invalid_correction`. Sellers mislabel across all of these; trust a
Correction over any marketplace field.

## A Correction freezes the listing

After `correct_enrichment` the listing is **frozen**: no later Enrichment
pass — automatic, fan-out, or a re-enrichment wave — touches the corrected
fields. Only the fields you send change; the rest of the record keeps its
values. There is no un-freeze in v1. To reopen a listing to AI enrichment,
issue a new Correction with the fields you now want set.

```json
{ "product_identity": "Dell OptiPlex 7080 i5-10500/16GB/512GB SSD",
  "condition": "complete",
  "bundle": [{ "description": "mouse", "confidence": "high" }] }
```

`product_identity` is a description string: an exact match wins, otherwise a
new Product Identity is minted and the listing is repointed to it. Bundle
items need a non-empty `description` and a `confidence` of
`high|medium|low|unknown`.

## Rejections

`create_rejection(search_id, listing_id, reason)` feeds the reason into the
next Sift's exclusion list, so the reason must say *why* — "not a Z440,
it's a Z230" — not just "no". A bare "no" poisons the exclusion list with
something the model cannot act on.

`restore_rejection` reverses it: the exclusion drops (only if no remaining
rejection shares that reason) and the listing becomes a match. Because the
identity's evidence just changed, follow with `run_search` so the verdicts
re-sift and `verdict_stale` clears.

## Authored descriptions

For an **Unidentified listing** — vague title, no model number — write what
you actually see in the photos and learn from the seller:
`patch_listing(id, authored_description="Dell OptiPlex 3060, i5-8500, 8GB, 256GB SSD")`.
The authored description overrides Enrichment and re-queues it, so the AI
now works from your description instead of the seller's guesswork.

## Duplicate identities

Same product under two identities = two half-filled price pools, and both
stay below the 5-observation floor that fair price needs.
`merge_identities(loser, into=winner)` re-points every listing, price
observation and search mapping at the winner in one transaction, then deletes
the loser. The winner's pool becomes the merged one, which is usually what
unblocks its fair price.

Pick the winner by which description better describes the thing, not by id.
If neither description is good, `patch_identity` the winner's description
after merging.

## Retune versus hand-edit

`retune_identity` asks the model to rewrite the description from all the
accumulated evidence. Use it when you have added real signal — corrections,
rejections, authored descriptions — and want the description to absorb it. It
sets `synthesized_at`; a blank or identical model reply is a no-op; a model
failure persists nothing.

`patch_identity` is a hand-edit. `synthesized_at` stays untouched, because
nothing was synthesized. Hand-edit when you know exactly what the description
should say; retune when the evidence should decide.

Either way, editing a description makes the verdicts over it stale
(`verdict_stale: true`). Follow with `run_search` to re-sift.

## Example sequence

A hunt returns cards that are wrong in the usual ways. One pass, in the order
that compounds best:

1. Read the page: `search_results(search_id=3, verdict="all")`. `all` so
   the mis-sifted listings are visible, not hidden.
2. Fix a wrong condition: `correct_enrichment(listing_id="offup:1234",
   condition="missing parts")`.
3. Fix a mis-resolved product: `correct_enrichment(listing_id="ebay:9876",
   product_identity="HP Z230 workstation", condition="complete")`.
4. Reject what is not the product at all: `create_rejection(search_id=3,
   listing_id="fb:555", reason="Z220, not the Z440")`.
5. Describe an **Unidentified listing** yourself:
   `patch_listing(id="offup:777", authored_description="Dell OptiPlex 3060, i5-8500, 8GB RAM, 256GB SSD")`.
6. Spot the duplicate pools — `list_identities` shows "HP Z440" and
   "HP Z440 Workstation" as separate rows: `merge_identities(identity_id=7,
   into=3)`.
7. Let the evidence work: `retune_identity(identity_id=3)` folds your
   corrections into the description, then `run_search(search_id=3)`
   re-sifts every listing against it.
8. Re-read `search_results(search_id=3)`. `fair_price` should now be present
   for the merged pool if it cleared 5 observations, and `verdict_stale`
   should be `false` across the re-sifted cards.
