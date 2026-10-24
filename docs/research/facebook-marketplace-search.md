# Facebook Marketplace — Programmatic Search Research (BoldTrader)

Researched 2026-10-23. Example query: "HP Z440". Sources at end; every claim cited. Items marked **UNVERIFIED** could not be confirmed against a primary source.

## TL;DR

- **No official buyer-side Marketplace search API.** One official search surface exists (Meta Content Library API) but is restricted to approved academic/nonprofit researchers; a commercial deal-finding app is ineligible. Everything else is seller-side push only.
- **ToS prohibits automated collection outright.** Meta Terms §3.2.3 + a dedicated Automated Data Collection policy + separate Automated Data Collection Terms all ban automated access without prior written permission. Meta runs a dedicated External Data Misuse (EDM) enforcement team.
- **Login wall is now mandatory** (2026): logged-out Marketplace search hard-redirects to login. Logged-in automation is the highest-risk configuration — account-disable reports cluster around it.
- **Legal picture is split:** logged-off scraping of truly public pages survived contract attack (Meta v. Bright Data, 2024); logged-in scraping, barrier circumvention, or post-C&D scraping produced losses (BrandTotal, Power Ventures).
- **Verdict: worst of the three target marketplaces** for this app. Recommend manual-assisted surface (paste listing → app analyzes) or paid third-party vendor, not automated crawling.

## 1. Official API: does Meta expose ANY official API for Marketplace search?

**Answer: No commercial buyer-side Marketplace search API exists. One official search surface exists (Meta Content Library API) but is restricted to approved academic/nonprofit researchers. Everything else is seller-side push only.**

### What Meta actually offers

| API | What it does | Useful for BoldTrader? |
|---|---|---|
| **Meta Content Library API** — `facebook/marketplace-listings/preview` | Real keyword search over public Marketplace listings: `q`, `CATEGORIES`, `LISTING_COUNTRIES`, `PRICE_MIN`/`PRICE_MAX`, `SINCE`/`UNTIL`, `SORT` (price, recency, views). Fields include `listing_details.title`, `listing_details.price.amount`, `listing_details.condition`, `listing_details.location`, `statistics.views`. | **Functionally yes, eligibility no** — see below |
| **Marketplace Partner Item API** (`POST /v20.0/{catalog-id}/items_batch`) | Push *your own* product catalog **into** Marketplace (create/update/delete listings). Rate limit: 30 calls/min, batches up to 300. | No — seller-side ingestion, not buyer search ([docs](https://developers.facebook.com/docs/marketplace/partnerships/itemAPI/)) |
| **Marketplace Partner Seller API** | Seller records for partner catalogs | No ([docs](https://developers.facebook.com/docs/marketplace/partnerships/sellerAPI/)) |
| **Graph API `/search`** | Public keyword search was killed in the 2018–2019 platform lockdown; deprecated endpoints list from Apr 30 2019 removed broad search surfaces ([changelog](https://developers.facebook.com/docs/graph-api/changelog/4-30-2019-endpoint-deprecations)). Current Graph API v26.0 has no Marketplace search node ([reference](https://developers.facebook.com/docs/graph-api/reference)) | No |
| **"Creator Marketplace Content"** (Graph v26.0) | Search/discovery of *creator digital content* (videos/photos), NOT used-goods Marketplace ([docs](https://developers.facebook.com/docs/graph-api/reference/creator-marketplace-content)) | No — name collision only |

### The Content Library catch
Meta Content Library and API genuinely indexes public Marketplace listings and supports exactly the query shape BoldTrader wants ([guide](https://developers.facebook.com/docs/content-library-and-api/content-library-api/guides/fb-marketplace/)). But:

- **Eligibility: qualified academic or nonprofit research institutions only.** Application reviewed by the Secure Data Access Center (CASD); 2–3 week review; must contribute to EU Digital Services Act systemic-risk research ([get-access](https://developers.facebook.com/docs/content-library-and-api/get-access)).
- A for-profit deal-finding app is **not eligible**. Applying under a false research purpose would be a material misrepresentation.
- Data lag: view counts refresh every 2–3 days; listings sold >1 month ago, stale >6 months, or privacy-restricted listings are excluded ([data dictionary](https://developers.facebook.com/docs/content-library-and-api/appendix/data-dictionary)).
- Rate limits: 60 queries/min (sync), 1 async query/min, 500,000 records per 7-day rolling budget per researcher ([rate limiting guide](https://developers.facebook.com/docs/content-library-and-api/content-library-api/guides/rate-limiting)).
- Third-party cleanroom (SOMAR VDE) compute becomes paid after 2025-12-31 ([Bellingcat note](https://bellingcat.gitbook.io/toolkit/more/all-tools/meta-content-library)).

**Verdict: For a commercial app, there is no official API. This matches the community consensus: "No official Marketplace API exists, which is why these scraping repos exist" ([Scrapfly roundup, Jul 2026](https://scrapfly.io/blog/posts/best-facebook-marketplace-scrapers-github)).**

## 2. Terms of Service: what do Meta's terms say about scraping/automated access?

Blunt: **every relevant clause prohibits this.**

1. **Meta Terms of Service §3.2.3**: "You may not access or collect data from our Products using automated means (without our prior permission) or attempt to access data you do not have permission to access, regardless of whether such automated access or collection is undertaken while logged-in to a Facebook account." ([facebook.com/terms](https://www.facebook.com/terms/)); quoted verbatim by Meta's developer policy ([Automated Data Collection](https://developers.facebook.com/documentation/development/terms-and-policies/automated-data-collection)).
2. **Meta developer "Automated Data Collection" policy** (updated Feb 3, 2025): "Platform APIs are the only allowable means to access data programmatically, unless you have our prior written permission. Using other tools and techniques to circumvent the protections we've placed on Platform Data constitutes a violation of Facebook's Terms of Service." Explicitly: allowable requests go **only to graph.facebook.com**; scripts/HTTP libraries/JS automating requests outside Platform APIs are disallowed "even if such technology is publicly available"; and the terms "still apply even if the conduct is not intentional or if you're unsuccessful."
3. **Automated Data Collection Terms** (separate contract, effective Oct 7, 2024, [facebook.com/apps/site_scraping_tos_terms.php](https://www.facebook.com/apps/site_scraping_tos_terms.php)): "You will not engage in Automated Data Collection without first obtaining Meta's express written permission." Permission is only for search-engine-style use; all other uses prohibited; includes audit rights, and Meta "may take enforcement action at any time... Enforcement can be both automated and manual," up to terminating your other agreements and accounts. Accepting these terms ≠ permission; permission requires a separate formal authorization.
4. **Commerce Seller Agreement** (May 26, 2026, [facebook.com/legal/commerce_product_merchant_agreement](https://www.facebook.com/legal/commerce_product_merchant_agreement)): incorporates ToS, Commercial Terms, Platform Terms, Data Terms; Meta reserves the right to suspend/terminate services at its discretion; Meta (not you) is granted the right to crawl/index your URLs.
5. **Meta's own framing of scraping**: "Unauthorized scraping is often done in a way that disguises the activity so that it blends in with ordinary usage" — and Meta maintains a dedicated **External Data Misuse (EDM) team** of data scientists/engineers doing rate limits, data limits, and "request blocking through pattern recognition" plus investigations and enforcement against accounts ([Facebook Help Center: Data scraping](https://www.facebook.com/help/463983701520800)).

**Practical ToS reading: automated Marketplace search without Meta's prior written permission is a contract violation by definition, and Meta reserves the right to ban accounts and revoke everything over it.**

## 3. Unofficial routes: what technically exists?

Two families, both documented:

### A. Internal GraphQL replay (no browser at runtime)
Facebook's web UI (Comet/Relay) calls `POST https://www.facebook.com/api/graphql/` with `doc_id`-keyed operations. Documented projects:

- **minzique/fb-cli** — "Unofficial Facebook Marketplace CLI — speaks Facebook's internal GraphQL with HAR/browser-imported cookies." Its [API.md](https://github.com/minzique/fb-cli/blob/main/docs/API.md) is the best public spec found:
  - Auth: cookies `c_user` + `xs` (critical), plus `datr`, `fr`, `sb`; CSRF tokens `fb_dtsg` (rotates ~weekly), `lsd`/`X-FB-LSD`, `jazoest` checksum; `__user`/`av` actor id.
  - Search ops: `CometMarketplaceSearchContentContainerQuery` (first page), `CometMarketplaceSearchContentPaginationQuery` (cursor pages), `MarketplacePDPContainerQuery` (listing detail), `MarketplaceSuggestionDataSourceQuery` (autocomplete).
  - Search variables: `bqf.query` (keyword), `filter_location_latitude/longitude`, `filter_radius_km`, `filter_price_lower_bound`/`filter_price_upper_bound` (integer cents), `commerce_search_and_rp_condition` (`NEW`/`USED_LIKE_NEW`/`USED_GOOD`/`USED_FAIR`), `commerce_search_and_rp_ctime_days` (1/7/30).
  - **Fragility: "Facebook rotates doc_ids on most deploys — refresh from a fresh HAR when fields stop populating."** Failure modes: HTTP 200 with empty body (rotated doc_id), `noncoercible_variable_value` (schema drift), HTTP 500 (missing `__crn`/`__comet_req`/stale `fb_dtsg`), "Login required" (expired cookies).
- **jdcodes1/facebook-marketplace-mcp** — same architecture; Chrome cookie extraction (macOS Keychain, AES-128-CBC); deliberately throttles to **3 requests/min "to avoid detection"** ([context.md](https://github.com/jdcodes1/facebook-marketplace-mcp/blob/master/context.md)).
- **jlsookiki/secondhand-mcp** and **kyleronayne/marketplace-api** — logged-out GraphQL search variants; note that "non-browser callers are sometimes handed a gated version of the search API (a single edge with a next-page cursor, or story stubs with no listing inside)" ([facebook.ts](https://raw.githubusercontent.com/jlsookiki/secondhand-mcp/411c05a59893fed65aa17c7f8acdbe67b749fc2e/src/marketplaces/facebook.ts)).

### B. Browser automation (Playwright)
- **danyk20/facebook-marketplace-scraper** (MIT, PyPI, 96% test coverage, [README](https://github.com/danyk20/facebook-marketplace-scraper)) — the most rigorous documentation of the 2026 reality:
  - **Login is now mandatory**: "anonymous visitors get redirected straight to the login page" (confirmed against fresh browser profiles, Oct 2026).
  - EU/EEA accounts hit a one-time Marketplace **data-usage consent screen**; scraper refuses to auto-click it.
  - **Search radius is account-controlled, not URL-controlled**: Facebook ignores the `radius` URL param and uses the account's saved radius; the scraper must change the account setting itself.
  - Facebook's sort changes *which* listings return, not just order (price sort returned 2 of 64 listings); big searches get truncated and must be split into price ranges to be complete.
  - Bare `requests` calls are blocked at the HTTP level; no callable JSON API without a browser-shaped session.
- **BoPeng/ai-marketplace-monitor** (274★, AGPL-3.0) — Playwright-based scheduled search + AI scoring + alerts; requires interactive Facebook login; Docker bundles noVNC "so you can solve logins and CAPTCHAs inside the container" ([Scrapfly review](https://scrapfly.io/blog/posts/best-facebook-marketplace-scrapers-github)).
- **hyuwowo/fb-marketplace-scraper** — playwright-stealth + browserforge fingerprints + Bezier mouse curves; cookie-file auth.
- **VIRUXE's standalone gist** — Playwright, pulls title/price/condition/description/location/seller for parts listings.
- **Dukeabaddon/specter** — for public *Pages* (not Marketplace) but documents the ecosystem collapse: "In late 2024, Meta permanently discontinued mbasic.facebook.com, which broke 95% of historical open-source Facebook scrapers" ([README](https://github.com/Dukeabaddon/specter)).

### C. Paid third-party scrapers
Apify actors ($1.20/1K listings, [thirdwatch/facebook-marketplace-scraper](https://apify.com/thirdwatch/facebook-marketplace-scraper)), Scrapfly, Bright Data, Captapi etc. These are commercial middlemen reselling scraped Marketplace data — they shift the technical burden but not the ToS/legal problem, and add cost + vendor dependency.

## 4. Bot detection: what is known?

- **Meta's own admission** (Help Center, [link](https://www.facebook.com/help/463983701520800)): dedicated External Data Misuse team; rate limits; data limits; "request blocking through pattern recognition... typically associated with automated computer activity"; active investigation of suspected scrapers; enforcement against associated accounts.
- **Login checkpoints / CAPTCHAs**: documented across projects — danyk20's scraper cannot pass 2FA/checkpoint with credentials and requires headed human login; BoPeng's monitor ships noVNC specifically to solve CAPTCHAs manually ([sources above](https://scrapfly.io/blog/posts/best-facebook-marketplace-scrapers-github)).
- **Device/cookie fingerprinting**: `datr` cookie is a long-lived device identifier (discussed in Facebook's own privacy litigation exhibits, [CourtListener exhibit](https://www.courtlistener.com/docket/7067512/1103/37/in-re-facebook-inc-consumer-privacy-user-profile-litigation)). fb-cli warns "mismatched UA + cookie can trigger checkpoints" ([API.md](https://github.com/minzique/fb-cli/blob/main/docs/API.md)).
- **Account disabling from automation**: specter's README: "Supplying personal authenticated cookies (c_user/xs) frequently triggers suspicious activity verification or permanent account disabling within 48 hours" ([README](https://github.com/Dukeabaddon/specter)). Independent corroboration: a `facebook-scraper` user reports "just from the first execution the account got disabled" ([issue #691](https://github.com/kevinzg/facebook-scraper/issues/691)); Marketplace sellers report "unusual activity" flags blocking listings ([reddit](https://www.reddit.com/r/FacebookMarketplace/comments/mw6nek/marketplace_account_flagged_due_to_unusual)).
- **Logged-out wall tightening**: as of mid/late 2026, Marketplace search hard-redirects cookie-less visitors to login ([danyk20 README](https://github.com/danyk20/facebook-marketplace-scraper); [Scrapfly](https://scrapfly.io/blog/posts/best-facebook-marketplace-scrapers-github)). The "no-login required" era of these tools is ending/ended; projects claiming keyless access (PyPI `facebook-marketplace-scraper`, Apify "no login") should be treated as UNVERIFIED against current behavior — several are exactly the profile of stale claims.
- **Academic literature**: anti-bot vendors and large platforms use browser fingerprinting and behavioral signals to detect automation without user-visible friction ([FP-Inconsistent, arXiv 2406.07647](https://arxiv.org/html/2406.07647); [Web Runner 2049](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338186)). Facebook-specific: [Hitchhiker's Guide to FB Web Tracking, ACM/CIM 2023](https://dl.acm.org/doi/fullHtml/10.1145/3543507.3583311).

## 5. Legal context

- **hiQ v. LinkedIn (9th Cir. 2022)**: scraping *publicly available* pages likely not a CFAA "authorization" violation ([opinion](https://cdn.ca9.uscourts.gov/datastore/opinions/2022-04-18/17-16783.pdf)). **Limits**: (a) narrow — it addresses CFAA only, not contract; (b) the case ended in a **settlement that largely conceded to LinkedIn** — hiQ shut down; the injunction never became a merits win ([Proskauer analysis](https://www.proskauer.com/blog/hiq-and-linkedin-reach-proposed-settlement-in-landmark-scraping-case)). (c) Van Buren (SCOTUS 2021) narrowed CFAA but courts still distinguish circumvention of technical barriers.
- **Meta v. Bright Data (N.D. Cal. 2024)**: Judge Chen granted Bright Data summary judgment — Meta's ToS, as drafted, did not prohibit **logged-off** scraping of public data; Meta then dropped the case ([order PDF](https://cases.justia.com/federal/district-courts/california/candce/3%3A2023cv00077/406956/181/0.pdf); [Quinn Emanuel analysis](https://www.quinnemanuel.com/media/n23fedyh/client-alert_-meta-v-bright-data-significant-decision-for-web-scraping-industry.pdf); [PR](https://www.prnewswire.com/news-releases/meta-files-notice-to-drop-web-scraping-case-against-bright-data-302071400.html)). **Key limit: this turned on the specific browsewrap wording and the logged-off/public posture — it is not a license for logged-in scraping or for scraping gated data.**
- **Meta v. BrandTotal (N.D. Cal.)**: judge ruled **against** the data harvester — Chrome-extension harvesting while logged in violated Meta's terms and anti-hacking laws; Meta won most claims ([CourtListener](https://www.courtlistener.com/opinion/9602199/meta-platforms-inc-v-brandtotal-ltd); [Courthouse News](https://www.courthousenews.com/judge-rules-brandtotals-data-harvesting-violates-metas-terms-of-use-and-anti-hacking-laws)).
- **Facebook v. Power Ventures (9th Cir. 2016)**: continuing to scrape **after a cease-and-desist**, while using credentials, = CFAA violation. A C&D converts a gray area into a bright line ([Apify analysis](https://blog.apify.com/facebook-v-power-ventures/)).
- **Meta's aggressive enforcement posture**: suits against Octopus Data (2022, [PCMag](https://au.pcmag.com/social-media/94957/meta-sues-company-with-ties-to-china-for-scraping-facebook-instagram-data)) and Voyager Labs (38,000 fake accounts used for scraping; [Courthouse News](https://v2.courthousenews.com/meta-can-proceed-with-data-scraping-suit-against-uk-surveillance-startup/)); C&Ds to Clearview AI ([report](https://www.medianama.com/2020-02-223-google-youtube-facebook-cease-and-desist-clearview)).
- **EU angle**: under DSA/French law, Meta's own CASD-reviewed research-access regime exists precisely because raw scraping of FB data by third parties is contested; Meta's Automated Data Collection Terms (Oct 2024) were tightened to close the "public data" loophole in contract terms ([terms text](https://www.facebook.com/apps/site_scraping_tos_terms.php)).

**Net legal picture: logged-off scraping of truly public pages has survived US contract attacks (Bright Data), but logged-in scraping, barrier circumvention, or post-C&D scraping has produced losses (BrandTotal, Power Ventures). Contract liability ≠ criminal liability, but Meta can and does ban accounts and sue. This is a summary of reported outcomes, not legal advice.**

## 6. Practical: if someone insists on automating FB Marketplace anyway

What the documented projects actually say:

1. **Expect a logged-in session.** Logged-out search is login-walled as of 2026 ([danyk20](https://github.com/danyk20/facebook-marketplace-scraper)). Logged-in automation is the highest-risk configuration: account disabling reports cluster around exactly this (specter: "within 48 hours"; facebook-scraper issue #691).
2. **Never run it on a primary personal account.** Every serious project uses throwaway accounts, exported cookies, or third-party sessions. If the account is also your identity (Messenger, groups, payments), assume collateral damage.
3. **Rate-limit aggressively.** The working projects self-throttle to ~3 req/min ([jdcodes1 context.md](https://github.com/jdcodes1/facebook-marketplace-mcp/blob/master/context.md)). Aggressive polling is the classic detection trigger.
4. **Expect breakage cadence.** doc_ids rotate on Facebook deploys; empty-200 responses mean recapture HAR; consent dialogs, radius settings, and sort behavior all deviate from documented API shapes ([fb-cli API.md](https://github.com/minzique/fb-cli/blob/main/docs/API.md), [danyk20 README](https://github.com/danyk20/facebook-marketplace-scraper)). Budget for ongoing maintenance as a first-class cost, not an exception path.
5. **Data completeness is worse than it looks.** Facebook truncates large result sets and its sort changes result membership; complete coverage requires splitting queries into price bands ([danyk20](https://github.com/danyk20/facebook-marketplace-scraper)).
6. **Risk profile summary**: ToS violation is certain (by Meta's own drafting); account loss is a matter of "when," not "if," at any meaningful volume; legal exposure is real but historically aimed at commercial-scale harvesters, not hobby-scale. The scraping-vendor ecosystem (Apify/Scrapfly/Bright Data) sells the same data with the risk outsourced to a vendor whose own ToS disclaims it — and Meta has sued vendors of exactly that kind.

### Recommendation for BoldTrader
Facebook Marketplace is the **worst** of the target marketplaces for this app: no official search API, explicit contractual prohibition, active dedicated anti-scraping enforcement, login walls, and high account-loss risk. If FB is on the roadmap, either (a) treat it as a manually-assisted surface (paste listing URL → app analyzes it, no crawling), (b) use a paid third-party data vendor and accept the churn/cost, or (c) deprioritize it in favor of marketplaces with real APIs. Do not build the core watch/deal pipeline's Facebook leg on logged-in scraping without explicit user consent about account risk.

## Sources

1. Meta Content Library — Marketplace search guide: https://developers.facebook.com/docs/content-library-and-api/content-library-api/guides/fb-marketplace/
2. Meta Content Library — Get access / eligibility: https://developers.facebook.com/docs/content-library-and-api/get-access
3. Meta Content Library — Data dictionary (Marketplace fields): https://developers.facebook.com/docs/content-library-and-api/appendix/data-dictionary
4. Meta Content Library — Rate limiting & query budget: https://developers.facebook.com/docs/content-library-and-api/content-library-api/guides/rate-limiting
5. Meta Content Library — Transparency Center page: https://transparency.meta.com/researchtools/meta-content-library
6. Marketplace Partner Item API (seller-side push): https://developers.facebook.com/docs/marketplace/partnerships/itemAPI/
7. Marketplace Partner Seller API: https://developers.facebook.com/docs/marketplace/partnerships/sellerAPI/
8. Meta Terms of Service (§3.2.3 automated access): https://www.facebook.com/terms/
9. Meta Automated Data Collection developer policy: https://developers.facebook.com/documentation/development/terms-and-policies/automated-data-collection
10. Meta Automated Data Collection Terms (contract): https://www.facebook.com/apps/site_scraping_tos_terms.php
11. Facebook Commerce Seller Agreement: https://www.facebook.com/legal/commerce_product_merchant_agreement
12. Facebook Help Center — Data scraping / EDM team: https://www.facebook.com/help/463983701520800
13. Graph API 2019 endpoint deprecations: https://developers.facebook.com/docs/graph-api/changelog/4-30-2019-endpoint-deprecations
14. Graph API reference v26.0 (no Marketplace search): https://developers.facebook.com/docs/graph-api/reference
15. minzique/fb-cli — reverse-engineered Marketplace GraphQL spec: https://github.com/minzique/fb-cli/blob/main/docs/API.md
16. jdcodes1/facebook-marketplace-mcp — architecture & fragility notes: https://github.com/jdcodes1/facebook-marketplace-mcp/blob/master/context.md
17. jlsookiki/secondhand-mcp — logged-out GraphQL + gating behavior: https://raw.githubusercontent.com/jlsookiki/secondhand-mcp/411c05a59893fed65aa17c7f8acdbe67b749fc2e/src/marketplaces/facebook.ts
18. danyk20/facebook-marketplace-scraper — login wall, consent, radius/sort quirks: https://github.com/danyk20/facebook-marketplace-scraper
19. Scrapfly — 5 Best OSS FB Marketplace Scrapers (Jul 2026): https://scrapfly.io/blog/posts/best-facebook-marketplace-scrapers-github
20. Dukeabaddon/specter — mbasic shutdown, cookie-replay bans: https://github.com/Dukeabaddon/specter
21. kevinzg/facebook-scraper issue #691 — account disabled first run: https://github.com/kevinzg/facebook-scraper/issues/691
22. Meta v. Bright Data, Order (N.D. Cal. Jan 23, 2024): https://cases.justia.com/federal/district-courts/california/candce/3%3A2023cv00077/406956/181/0.pdf
23. Quinn Emanuel — Meta v. Bright Data analysis: https://www.quinnemanuel.com/media/n23fedyh/client-alert_-meta-v-bright-data-significant-decision-for-web-scraping-industry.pdf
24. hiQ v. LinkedIn, 9th Cir. opinion (2022): https://cdn.ca9.uscourts.gov/datastore/opinions/2022-04-18/17-16783.pdf
25. Proskauer — hiQ/LinkedIn settlement: https://www.proskauer.com/blog/hiq-and-linkedin-reach-proposed-settlement-in-landmark-scraping-case
26. Meta v. BrandTotal order: https://www.courtlistener.com/opinion/9602199/meta-platforms-inc-v-brandtotal-ltd
27. Facebook v. Power Ventures analysis (C&D + CFAA): https://blog.apify.com/facebook-v-power-ventures/
28. Meta v. Octopus Data: https://au.pcmag.com/social-media/94957/meta-sues-company-with-ties-to-china-for-scraping-facebook-instagram-data
29. Meta v. Voyager Labs: https://v2.courthousenews.com/meta-can-proceed-with-data-scraping-suit-against-uk-surveillance-startup/
30. FP-Inconsistent — fingerprint-based bot detection: https://arxiv.org/html/2406.07647
31. Hitchhiker's Guide to Facebook Web Tracking (ACM CIM 2023): https://dl.acm.org/doi/fullHtml/10.1145/3543507.3583311
32. datr cookies — FB privacy litigation exhibit: https://www.courtlistener.com/docket/7067512/1103/37/in-re-facebook-inc-consumer-privacy-user-profile-litigation
33. Bellingcat — MCL SOMAR compute fee change: https://bellingcat.gitbook.io/toolkit/more/all-tools/meta-content-library
34. Apify thirdwatch Marketplace actor: https://apify.com/thirdwatch/facebook-marketplace-scraper

## UNVERIFIED items
- Current (Oct 2026) behavior of "keyless" scrapers (PyPI `facebook-marketplace-scraper`, Apify no-login claims) — not run; multiple sources say logged-out search is now login-walled, so treat keyless claims as suspect until tested.
- Whether Meta's Content Library Marketplace coverage includes all regions/verticals relevant to BoldTrader's markets — docs say "most countries" with a limited set excluded for compliance review; exact list not published.
- Whether Meta's 2026 ToS revisions changed the §3.2.3 numbering (Meta renumbered terms in 2025–2026 rewrites; the quoted automated-access prohibition is current, the section number may drift).
- Exact detection thresholds (requests/min that trigger checkpoints) — undocumented; community numbers (e.g., 3 req/min) are folklore, not sourced from Meta.
