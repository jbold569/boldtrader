# OfferUp — Programmatic Listing Search Research (BoldTrader)

Researched 2026-10-23. Example query: "HP Z440". Sources at end; every claim cited. Items marked **UNVERIFIED** could not be confirmed against a primary source.

## TL;DR

- **No official API.** OfferUp has no public developer API for listings. `offerup.com/api/docs` returns HTTP 410 (Gone). Multiple independent projects and vendor docs confirm "OfferUp does not offer a public listings API." [1][2][3]
- **The working route is the internal GraphQL API** at `https://offerup.com/api/graphql`, operation `GetModularFeed`. Search works **anonymously** — no login, no cookies; a client-minted device token (`x-ou-d-token: web-<random hex>`) suffices. Notably, OfferUp's own robots.txt **explicitly allows `/api/graphql$`** while disallowing `/search` and `/api/` generally. [4][5][6]
- **ToS explicitly prohibits scraping**: §7 bans "any type of automated means to… collect or extract data from OfferUp" and third-party apps without written consent. This is a contractual risk, not a technical one — enforcement against read-only browsers is undocumented. [7]
- **No sold/completed-listing data.** OfferUp does not expose sold prices to search at all (confirmed by Soldgraph: "Sold search and completed sale prices are not supported"). Your fair-price model cannot source sold comps from OfferUp; it must come from another marketplace. [8]
- **Practical for Z440 hunting**: keyword `q="HP Z440"` + lat/lon + `sort=newest` + `radius` (max 50 mi) is the core search. ~44–50 listings per page, cursor pagination, ~220-item practical cap per search. Condition/price-firm/description require a second per-listing detail call. [9][10]
- **Anti-bot posture is real but manageable at low volume**: datacenter IPs blocked, Cloudflare-style challenges reported, per-IP shadow-bans after ~5–10 rapid search pages. Anonymous read-only search from a residential IP at human-ish cadence is the documented safe pattern. [11][12]

## 1. Official API: none

| Check | Result |
|---|---|
| `https://offerup.com/api/docs` | **HTTP 410 Gone** as of 2026-10-23 (direct fetch). Once advertised; now dead. [1] |
| Help Center (help.offerup.com) | No developer/API article exists; searches for "API developer third-party" return only buying/selling/support articles. [13] |
| OfferUp for Business / dealer terms | `business.offerup.com/seller-terms` grants posting rights to dealers — **no API grant**. [14] |
| Partner program | `about.offerup.com/partnerterms` exists (general partner terms) — implies consent-based partnerships, not open self-serve API. [15] |
| Third-party consensus | planetzero/offerup: "OfferUp doesn't provide an API." [2] ParseBird actor FAQ: "OfferUp does not offer a public listings API." [5] Haketa: "OfferUp does not offer a public data API." [11] |

**Conclusion: there is no official, sanctioned programmatic search. Everything below is unofficial.**

## 2. Unofficial API: internal GraphQL (`GetModularFeed`)

### 2.1 Current web API (2024+)

- **Endpoint:** `POST https://offerup.com/api/graphql` (same-origin as the site; the web SPA's own backend). [4][6]
- **Operation:** `GetModularFeed($searchParams: [SearchParam], $debug: Boolean)` — this is OfferUp's search-results feed; keyword search is just a feed with a `q` param. Full query document captured in grail-monitor's `offerup_query.graphql`. [4]
- **Auth for search: none.** Per grail-monitor: "reachable with a plain HTTP client — no login. It authenticates with a client-generated device token (a random `web-<hex>` id), not a server-issued credential." [4] Crowdpull actor: "Establishes an anonymous session with OfferUp — no login, no cookies, no browser." [6]
- **Required headers** (from grail implementation [4]):
  - `Content-Type: application/json`
  - `User-Agent`: a normal desktop browser UA
  - `x-ou-operation-name: GetModularFeed`
  - `x-ou-d-token: web-<56 hex chars>` (minted locally via `secrets.token_hex(28)`)
  - `x-ou-version: 2026.1.0`
  - `x-ou-usercontext`: JSON `{device_id, user_agent, app_version, device_platform:"web"}`
- **Search params** (`searchParams` key/value pairs) [4]:
  - `q` — keyword text (e.g. `"HP Z440"`)
  - `lat`, `lon` — search center (strings)
  - `limit` — page size (impl uses 50)
  - `page_cursor` — next-page cursor from previous response's `pageCursor`
  - `platform: "web"`
  - (Legacy REST also exposed `radius`, `price_min`, `price_max`, `sort`, `condition`, `delivery_param` — see §2.2; ReefAPI/Soldgraph confirm these filters exist on the current feed: radius 5/10/20/30/50, price_min/max, sort, condition, category.) [9][8]
- **Response shape:** `data.modularFeed` → `looseTiles[]` / `modules[]` containing `ModularFeedListing` tiles with `listingId`, `title`, `price`, `locationName`, `image`, `conditionText`, `flags` (e.g. `LOCAL_PICKUP`), plus `pageCursor`, `filters`, `searchAlert`, and analytics IDs. [4][9]
- **Detail call:** each listing's full record (description, condition, posted_at, photos, seller profile incl. items_sold/joined/badges, shipping terms, category path) comes from the listing-detail query — ReefAPI wraps it as `product/detail`, ParseBird as `fetchDetails`. [9][10]

### 2.2 Legacy REST (2017–2018 era, historical reference)

planetzero/offerup (npm `offerup`) documented `getFullListByQuery({location, search, radius, limit, price_min, price_max})` returning `feed_items[]` with `post_date`, `category`, `condition`, `price`, lat/lon, images; sort values `distance`, `-posted` (Newest), `price`, `-price`; radius options 5/10/20/30/50. [2][16] **Current status of this REST surface: UNVERIFIED** — the project is from 2018 and current projects all use GraphQL.

### 2.3 Documented open-source projects

| Project | What it demonstrates |
|---|---|
| `jakedamico/grail-monitor` (Python) | Anonymous `GetModularFeed` search via httpx; device-token minting; cursor paging; 403/429 handling. Closest analog to BoldTrader's need. [4] |
| `planetzero/offerup` (JS, 2018) | Legacy REST search + item detail + user profile. [2] |
| `everettcaldwell/unofficial-offerup-api` (Python) | `client-graphql.offerup.com` GraphQL: login (email+MFA), `getTaxonomy` (category tree by ZIP — **no session cookie required**), listing creation mutations. [17] |
| `everettperiman/OfferupUnofficalAPI` (Python) | Search param table: `radius` 5/10/20/30/50, `price_min/max`, `q`, `delivery_param` (p/s/p_s), `limit` (~400 API-side cap), `lat/lon`, `sort` (`-posted` newest). Warns: "limit API calls to > 1s, they will block your requests if they are too fast." [18] |
| `oscar0812/pyOfferUp` (PyPI) | Anonymous search by query+city/state or lat/lon; returns listingId, price, title, locationName, image, flags. [19] |

### 2.4 Commercial wrappers (if you'd rather not own the unofficial client)

- **ReefAPI** — `POST /offerup/v1/search` + `/offerup/v1/product/detail`, `x-api-key` auth, 1 credit/call, 1,000 free credits. Params: `query, category, zip_code, latitude, longitude, radius, price_min, price_max, sort, cursor, max_rotations`. Measured: ~44–50 rows/page; condition & firm-price are **null on search tiles** (0 of 704 rows) — need detail call. [9]
- **Soldgraph** — `GET /v1/offerup/listings` (q, zip/lat/lon, radius, category, condition, price, sort, cursor) + `/v1/offerup/item`. Explicitly: **no sold search, no completed sale prices**. ~50/page; paging ends ~220 listings or page 50; 15-min cache; 202-job polling on cache miss. [8]
- **Apify actors** — many (parsebird, crowdpull, haketa, igolaizola…), $1–3.50 per 1,000 results, residential proxies included. [5][6][11]

## 3. Bot detection & rate limiting

**What is documented (secondary sources — maintainers' reports):**

- **Datacenter IPs blocked instantly** — HTTP 403 from AWS/GCP/Azure/OVH/Hetzner/Linode ranges (Haketa claim [11]; ParseBird: "OfferUp blocks datacenter IPs, so Residential proxy is used by default" [5]).
- **Cloudflare-style JS challenge** on cold visits + **TLS fingerprint inspection** rejecting bare `requests`/`fetch` (Haketa [11]). **Partially contradicted** by grail-monitor and crowdpull, which do plain-HTTP GraphQL POSTs successfully [4][6] — challenge intensity likely varies by IP reputation and has changed over time. Treat as: *may* challenge; a challenge-resistant HTTP client (or residential IP) is the mitigation.
- **Per-IP rate ceilings:** "5–10 search pages from a single IP and you're shadow-blocked for hours" (Haketa [11]); ">1s between calls or blocked" (Everett [18]). **No official rate-limit numbers exist — UNVERIFIED.**
- **CAPTCHA escalation** (hCaptcha) for repeat offenders (Haketa [11]).
- **Geofencing:** non-US IPs see stripped/redirected UX (Haketa [11]); OfferUp is US-only per its own ToS §3 (US residents only) [7] and vendor docs [8].
- **403 = rate-limited/blocked** (grail treats 403/429/5xx as transient and retries with backoff) [4].

**What OfferUp itself says:** nothing published about rate limits or bot systems. robots.txt is the only machine-readable signal: it disallows `/api/`, `/search`, `*q=`, `*sort=`, `*radius=`, `*price_min=`, `*price_max=`, `*condition=`, `*delivery_param=`, and explicitly disallows `wget`, `Nutch`, `AhrefsBot`, `Crawlera` etc. ("Bot, bot, go away…"), while **allowing `/api/graphql$`** — i.e., the GraphQL endpoint is deliberately not robots-blocked. [12]

## 4. Terms of Service (offerup.com/terms, last updated July 21, 2026)

Directly relevant clauses, §7 "Prohibited Conduct" [7]:

1. *"Use any type of automated means to utilize the OfferUp Services or to collect or extract data from OfferUp, such as a harvesting bot, robot, script, crawler, or scraper, not provided by OfferUp"* — **explicit blanket ban on automated data collection.**
2. *"Develop or use any third-party applications that interact with the OfferUp Services without OfferUp's prior written consent."*
3. *"Reverse engineer any aspect of our Services or do anything that might discover source code or bypass or circumvent measures employed to prevent or limit access to any part of our Services."* — relevant if you route around challenges.
4. *"Copy, reproduce, distribute… all or portions of our Services, including our underlying content."*
5. Enforcement: *"OfferUp may suspend or terminate your right to access the Services"*; §9 allows termination "for any reason without notice at OfferUp's sole discretion." [7]

Also: §2 eligibility requires US residence and no prior suspension [7]. Disputes go to individual JAMS arbitration under Washington law (§21) [7]. There is **no** "personal use" exception. **Bottom line: BoldTrader's OfferUp scraping violates ToS as written.** This is standard for classifieds-scraping apps; the practical exposure is account/IP-level, not litigation, for read-only low-volume use — but that is a business decision, not a legal clearance. **UNVERIFIED:** whether OfferUp has ever pursued legal action against read-only scrapers.

## 5. Practical: HP Z440 on OfferUp

### 5.1 Locality model
- Search is **geo-scoped by lat/lon** (or ZIP resolved via OfferUp's own geocoder). There is **no nationwide search**; omitting location falls back to the geographic center of the US (Pretty Prairie, KS) [9]. Max radius **50 miles** for general items (25/80/100/200/nationwide only for vehicles) [8][9].
- Implication for BoldTrader: each "watch" needs a metro center; multi-metro coverage = multiple searches per cycle.

### 5.2 Categories
- Two-level dotted taxonomy: `1` Electronics & Media, `2` Home & Garden, `5` Vehicles, `12` Business equipment, `14` General, etc.; subcategories like `1.2` Cell phones, `1.6` Computers & Accessories (web URL `/c/computers-and-accessories` and explore path `/explore/k/1/6` correspond) [8][9][20].
- Full tree retrievable anonymously via GraphQL `getTaxonomy(input:{zipcode})` — no session cookie required [17].
- **Caveat (measured by ReefAPI):** when both `q` and `category` are given, category can override keyword where local supply is thin — prefer keyword-only search [9].

### 5.3 Title conventions for "HP Z440"
- Titles are free-text seller-written. Observed desktop-title pattern on OfferUp computer listings: `"HP OMEN 870-224 Gaming Desktop — Intel i5, GTX 1060, 1TB"` — brand + model + spec string [20]. For Z440 you should expect variants: "HP Z440", "HP Z440 Workstation", "Z440 Xeon E5-2620 v3", bundles with GPU/SSD mentioned in title or description. **Specific Z440 title statistics: UNVERIFIED** (not scraped during this research).
- Search tiles give title + price + town only. **Condition, firm-price, description, post date are NOT on the feed tile** (measured 0/704 rows for condition/firm-price [9]) — you need one detail request per candidate listing to get description/condition/posted_at/seller stats. [9][10]

### 5.4 Freshness / sort-by-newest
- **Yes**: `sort=newest` exists (legacy `-posted`), alongside `best_match`, `closest`, `price_asc`, `price_desc`. All five verified to change result sets. [9][8][16]
- Search tiles do **not** include post dates; detail records include `posted_at`/`postDate` [9][6]. Freshness filtering ("newer than N hours") requires detail fetch (crowdpull limitation [6]).
- Practical polling pattern: `q="HP Z440"`, `sort=newest`, radius per metro, poll every N minutes, dedup by `listingId`.

### 5.5 Sold data — critical gap
- **OfferUp exposes no sold/completed listings to search.** Soldgraph: "Sold search and completed sale prices are not supported; `/v1/offerup/sold` is not an API endpoint." [8] Sellers can archive sold items, removing them from search [21]. Detail pages show a seller's *count* of items sold, not prices [9].
- **Implication:** BoldTrader's "fair price per product+condition from pooled sold data" cannot be built from OfferUp. Sold comps must come from eBay (Marketplace Insights / third-party) and OfferUp contributes only live asking prices. This matches the concern already flagged in `docs/research/ebay-search-apis.md`.

## 6. Risk profile

| Dimension | Assessment |
|---|---|
| ToS violation | **Certain.** §7 explicitly bans automated scraping and third-party apps without written consent [7]. |
| Account risk (authenticated) | Real. OfferUp suspends accounts for guideline violations, sometimes in error (Reddit reports of mass ToS-violation emails and wrongful suspensions [22][23]). **Do not run scraping on a personal buying account.** |
| IP risk (anonymous) | Documented: shadow-bans after ~5–10 rapid pages [11]; datacenter ranges blocked outright [5][11]. Mitigated by residential IP + ≥1–2s pacing + backoff on 403/429 [4][18]. |
| Search-only vs authenticated | **Search-only is materially safer.** All documented anonymous search works with no account [4][6][19]; ToS still prohibits it, but there is no account to lose, and OfferUp's public search is browsable by anyone. Authenticated automation adds account jeopardy with zero search benefit (search needs no auth). |
| Legal | hiQ v. LinkedIn supports scraping public data [5], but OfferUp's explicit contractual ban + CFAA-gray "circumvent access measures" clause (§7) makes it riskier than robots-respecting scraping. **UNVERIFIED:** any actual enforcement action by OfferUp against scrapers. |
| Vendor churn | The GraphQL schema and defenses change ("internal API changes every few weeks" per Haketa [11]). Budget for breakage; a commercial wrapper (ReefAPI/Soldgraph) transfers that risk for ~$1–3.50/1k results. [8][9] |

**Recommendation for BoldTrader:** anonymous `GetModularFeed` search (q + lat/lon + sort=newest), residential exit IP, 1–2s pacing, per-metro watches, detail-fetch only candidates that pass a title screen; never authenticate; treat sold-price data as unavailable from OfferUp.

## Sources

1. `https://offerup.com/api/docs` — direct fetch 2026-10-23: HTTP 410 Gone.
2. planetzero/offerup README — https://github.com/planetzero/offerup/blob/master/README.md
3. apis.io provider profile — https://apis.io/providers/offerup
4. jakedamico/grail-monitor — https://github.com/jakedamico/grail-monitor/blob/master/grail/providers/offerup.py and `offerup_query.graphql`
5. ParseBird OfferUp Scraper (Apify) — https://apify.com/parsebird/offerup-scraper/api
6. crowdpull/offerup-scraper — https://apify.com/crowdpull/offerup-scraper/api
7. OfferUp Terms of Service (July 21, 2026) — https://offerup.com/terms
8. Soldgraph OfferUp listings docs — https://soldgraph.com/docs/api/offerup-listings
9. ReefAPI OfferUp docs — https://reefapi.com/docs/offerup and https://reefapi.com/offerup-api
10. ReefAPI product/detail response fields — same as [9].
11. haketa/offerup-scraper — https://apify.com/haketa/offerup-scraper
12. OfferUp robots.txt — https://offerup.com/robots.txt
13. help.offerup.com search results for API/developer — no developer API article exists (searched 2026-10-23).
14. OfferUp for Business ToS — https://business.offerup.com/seller-terms
15. OfferUp Partner Program General Terms — https://about.offerup.com/partnerterms
16. planetzero getFullListByQuery docs — https://github.com/planetzero/offerup/blob/master/docs/getFullListByQuery.md
17. everettcaldwell/unofficial-offerup-api — https://github.com/everettcaldwell/unofficial-offerup-api/blob/main/offerup_graphql.py
18. everettperiman/OfferupUnofficalAPI README — https://github.com/everettperiman/OfferupUnofficalAPI
19. pyOfferUp — https://pypi.org/project/pyOfferUp/ and https://github.com/oscar0812/pyOfferUp
20. OfferUp Computers & Accessories pages — https://offerup.com/c/computers-and-accessories and https://offerup.com/explore/k/1/6
21. OfferUp Help: "Update an item listing" — https://help.offerup.com/hc/en-us/articles/360032335951-Update-an-item-listing
22. r/offerup "Account suspended" — https://www.reddit.com/r/offerup/comments/149nn34/account_suspended
23. r/offerup "My Account says locked" — https://www.reddit.com/r/offerup/comments/1g0zsgq/my_account_says_locked
24. OfferUp Help: "Why accounts are suspended or removed" — https://help.offerup.com/hc/en-us/articles/50394859688724-Why-accounts-are-suspended-or-removed
