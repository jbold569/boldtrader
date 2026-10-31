---
name: daily-sweep
description: Run the daily pass over every Bargain Search — re-fan each one, read the fresh deals, and triage what the market brought in overnight.
---

# Daily sweep

Deals arrive in **waves** — corporate decommissioning cycles dump pallets of
the same machine at the same time, then supply thins out. The sweep is how
you catch a wave instead of missing it: one pass over every live hunt, each
morning.

## When to use

A scheduled or on-demand pass over the whole board. Also the right skill when
the user asks "what's out there today" or "did anything come in".

## Tools

| Tool | What it does here |
|---|---|
| `list_searches` | Every Bargain Search with `status` and `match_count` |
| `run_search` | Re-fan one search without touching its draft |
| `get_search` | Poll one search until `complete` |
| `list_deals` | The flat deal feed across every product |
| `search_results` | One search's cards, for a closer look |
| `reenrich_search` | Recover the Enrichment rows that failed |

## Example sequence

1. `list_searches` for the board. Note `status` and `match_count` per
   search — a search sitting at `match_count: 2` has a net too narrow to
   catch a wave.
2. `run_search(search_id=…)` for each live search. This re-fans out to the
   marketplaces without bumping the draft's `version`. Fan-out runs in the
   background; the call returns immediately.
3. `get_search(search_id=…)` until each is `complete`. Do not read results
   at `enriching`: half the cards have no Enrichment yet and will look
   empty. The sweep is worth the wait.
4. `list_deals(sort="margin_desc", availability="live")` for the flat
   feed across every product. This is the morning's answer: nothing, or a
   list with a shape.
5. `reenrich_search(search_id=…)` on any search where cards came back with
   `enrichment.status: "failed"`. It only re-queues missing or failed rows,
   never overwrites good ones, so it is safe to fire blindly and repeat.
6. Triage: reject what is wrong with a reason that says why; correct
   conditions and bundles that Enrichment got wrong (`correcting-data`).
   Those corrections feed tomorrow's synthesis.

## Reading the sweep

**Nothing came in.** Normal between waves. If the same three searches come
back empty every day for a week, the problem is the queries, not the market
— widen them with plain layperson terms and see `hunting-a-product`.

**A cluster arrived.** Same product, many listings, similar price = a wave.
This is the moment to move: work the feed by margin, look at condition
first, and remember a big bundle can make a bad-looking ask a good deal via
**flip value** (already folded into `effective_price`).

**A price surge.** If everything for a product is priced *at* the level you
used to call a deal, that is a **price surge**, not a drought: the market
moved. Do not "fix" the threshold to make old deals reappear. Fair price
tracks the trailing 90 days, so it catches up on its own as the observations
roll forward.

## Failure modes

Fan-out tolerates a single marketplace failing — it is a note in
`failed_marketplaces`, not an error. A sweep where one marketplace is
consistently failing is a real problem (session expiry, IP block) worth
flagging; one that blips occasionally is not.

Never delete a search to "reset" it. `run_search` is the reset.
`delete_search` is irreversible.
