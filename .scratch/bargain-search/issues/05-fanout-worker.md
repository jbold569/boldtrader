# 05 — Fan-out + enrichment worker

Status: ready-for-agent

On Bargain Search confirmation: run all curated queries across eBay/OfferUp/FB (paginated, parallel, tolerant of single-marketplace failure — same pattern as `_search_all`). Persist every new listing to `listings` (dedupe by `marketplace:listing_id`).

Enrichment worker: background loop picks `pending` enrichment rows (match/unsure from triage), calls `fetch_detail` + `enrich`, writes result, retries once on failure then marks `failed`. Concurrency 1. Restart-resumable (status columns are the queue).

Progress: `running 34/120` counters on the Bargain Search row, visible in the list page.

Verify: create a small Bargain Search (2 queries, 1 marketplace), watch the queue drain, check enrichment rows land. Kill the server mid-run, restart, confirm it resumes.
