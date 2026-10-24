# Interim eBay scraping until API access lands

We have no eBay developer keyset yet, so the MVP's eBay integration is a primitive scraper of the public search pages rather than the official Browse API decided in ADR 0003. This is a deliberate, temporary deviation: scraping violates eBay's robots.txt and API License Agreement, and the Browse API needs no EPN approval for basic search — a free keyset works day one. We chose the scraper to keep momentum now, not because it is the right long-term path.

**Consequences:** the scraper is fragile (markup changes, IP blocks) and carries contract-level risk. All access goes through the `Marketplace` interface so `EbayScraper` can be swapped for an `EbayBrowseApi` implementation without touching the server or data shapes. When the keyset arrives, replace the scraper; do not "fix" the scraper into permanence.
