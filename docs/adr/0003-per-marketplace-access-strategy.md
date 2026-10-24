# Per-marketplace access strategy: official API, anonymous unofficial, and manual-assisted

Research across eBay, OfferUp, and Facebook Marketplace (see `docs/research/`) found the three marketplaces sit at radically different positions on the sanctioned-access spectrum, so a single ingestion pattern is impossible. We decided per-marketplace:

- **eBay: official Browse API.** Sanctioned, app-only OAuth, keyword/category/condition/local-pickup filters, 5,000 calls/day default. The only marketplace where we build on first-party infrastructure.
- **OfferUp: unofficial anonymous GraphQL** (`GetModularFeed`). No official API exists; the internal endpoint works without login, and its robots.txt explicitly allows `/api/graphql$`. We search anonymously, never authenticate, pace at human cadence from a residential IP, and treat the endpoint as subject to change every few weeks. ToS prohibits it as written; we accept contract-level risk for read-only, no-account search.
- **Facebook Marketplace: manual-assisted only.** No buyer-side API; Meta's terms ban automated collection outright and it runs a dedicated anti-scraping enforcement team; logged-out search is login-walled and logged-in automation gets accounts disabled within days. The app analyzes listing content the user brings to it (pasted listing/URL/screenshots); it does not crawl Facebook.

**Sold-data fallback (folded in):** only eBay exposes sold data, and its official route (Marketplace Insights API) is closed to new applicants. Fair price therefore bootstraps from live asking prices with a conservative discount factor until sold data lands — via EPN partner approval or a vetted third-party vendor. The pipeline must degrade gracefully when sold data is absent rather than hard-depend on it.

Rejected: uniform scraping across all three (Facebook's enforcement makes this reckless), and dropping Facebook entirely (it's a real supply source for local deals — just not a crawlable one). This maps each marketplace to the most aggressive access its risk posture safely permits.
