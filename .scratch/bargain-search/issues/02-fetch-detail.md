# 02 — fetch_detail per marketplace

Status: ready-for-agent

Add `fetch_detail(listing) -> ListingDetail` to the `Marketplace` ABC (`src/marketplace.py`). ListingDetail: full description text, images, shipping/fee fields where exposed.

- **eBay**: public listing page fetch + parse. Trivial.
- **OfferUp**: GraphQL detail query — verify anonymous access works before committing code.
- **Facebook**: via existing Playwright path; best-effort.

Failure contract: a marketplace that can't return detail raises; callers degrade that listing to triage-only with "enrichment unavailable". One marketplace never blocks the pipeline.

Verify: one real listing per marketplace, print the detail record.
