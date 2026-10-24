# 05 — Fan-out + enrichment worker

Status: ready-for-agent

On Bargain Search confirmation: run all curated queries across eBay/OfferUp/FB (paginated, parallel, tolerant of single-marketplace failure — same pattern as `_search_all`). Persist every new listing to `listings` (dedupe by `marketplace:listing_id`).

Enrichment worker: background loop picks `pending` enrichment rows (match/unsure from triage), calls `fetch_detail` + `enrich`, writes result, retries once on failure then marks `failed`. Concurrency 1. Restart-resumable (status columns are the queue).

Progress: `running 34/120` counters on the Bargain Search row, visible in the list page.

Verify: create a small Bargain Search (2 queries, 1 marketplace), watch the queue drain, check enrichment rows land. Kill the server mid-run, restart, confirm it resumes.

## Comments

Built `src/fanout.py`: `fan_out()` (one thread per marketplace, paginated, tolerant of single-marketplace failure) persists each new listing to `listings` (dedupe by `marketplace:listing_id`) and triages it; match/unsure listings enter the `enrichments` queue as `pending`. `enrichment_worker()` is a concurrency-1 loop that picks `pending` rows, calls `fetch_detail` + `enrich`, retries once, then marks `failed`.

Search status flow: `running` (fan-out in progress) → `enriching` (fan-out done, enrichment pending) → `complete` (queue drained). The `listing_ids` column on `bargain_searches` holds the JSON list of queued listing ids (the progress denominator); done = total − pending. The `running 34/120` rendering itself is ticket 06's list page.

`init_db` now migrates pre-existing DBs missing `listing_ids` via `ALTER TABLE`. `server.py` registers `Handler.fanout_marketplaces` (eBay/OfferUp/FB) separate from the search page's set, spawns `fan_out` on `/confirm`, and starts `enrichment_worker` in `main()`.

Verified live (OfferUp, 2 queries, Dallas): fan-out persisted 31 listings, queued 30 (match/unsure), status → `enriching`; worker drained 30/30 to `enriched`, status → `complete`, zero failures. Restart-resume confirmed: killed the server mid-run (8 pending), restarted, worker resumed and drained the remainder. HTTP `/confirm` path exercised end-to-end. eBay returns 403 (Akamai) from this IP today — tolerated as a single-marketplace failure per spec.
