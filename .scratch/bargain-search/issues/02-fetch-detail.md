# 02 — fetch_detail per marketplace

Status: ready-for-agent

Add `fetch_detail(listing) -> ListingDetail` to the `Marketplace` ABC (`src/marketplace.py`). ListingDetail: full description text, images, shipping/fee fields where exposed.

- **eBay**: public listing page fetch + parse. Trivial.
- **OfferUp**: GraphQL detail query — verify anonymous access works before committing code.
- **Facebook**: via existing Playwright path; best-effort.

Failure contract: a marketplace that can't return detail raises; callers degrade that listing to triage-only with "enrichment unavailable". One marketplace never blocks the pipeline.
Verify: one real listing per marketplace, print the detail record.


## Comments

Built (2026-10-24):
- `src/marketplace.py`: added `ListingDetail` dataclass (description, images, shipping_cost) and `fetch_detail(listing) -> ListingDetail` on the `Marketplace` ABC. Concrete default raises `NotImplementedError` so non-detail marketplaces (DDG mock) stay instantiable; callers degrade those listings to triage-only.
- `src/ebay_scraper.py`: `fetch_detail` fetches the public item page, pulls the seller description from the `itm.ebaydesc.com` iframe (eBay hosts it cross-origin), collects `s-l1600`/`$_1` gallery images, parses shipping cost from the shipping section ("Free" → 0.0).
- `src/offerup_scraper.py`: `fetch_detail` via GraphQL `listing(listingId: ID!)` — description, photos, `shippingRate { price }`. Anonymous access verified live before committing (minted `x-ou-d-token`, no login).
- `src/facebook_scraper.py`: `fetch_detail` via existing Playwright persistent-profile path; reads `og:description` + `og:image` meta tags (far more stable than FB's rotating DOM classes). FB exposes no shipping/fees → `shipping_cost=None`.

Ran: live verify against one real listing per marketplace (HP Z440 / Dell Optiplex searches). All three returned full description, images, and shipping where exposed; DDG mock raises `NotImplementedError` as required.

Notes:
- eBay's Akamai intermittently 403s this IP (worked earlier same day, flaky now). The retry lives in the caller per the failure contract — a marketplace that can't return detail raises, and the pipeline degrades that listing. Verified by retrying until a good page arrived.
- OfferUp `shippingRate.price` is null for local-pickup-only listings; that's a genuine "not exposed", not a parse failure.
