# eBay — Programmatic Listing Search Research (BoldTrader)

Researched 2026-10-23 against developer.ebay.com primary sources. Example query: "HP Z440".

## TL;DR

- **Live-listing search: Browse API** (`GET https://api.ebay.com/buy/browse/v1/item_summary/search`). App-only OAuth (client credentials), no user login needed. Keyword, category, price, condition, and **local-pickup radius** filters all documented. Default 5,000 calls/day.
- **Sold/completed data: Marketplace Insights API** (`GET /buy/marketplace_insights/v1_beta/item_sales/search`) — 90-day sold history, but **Limited Release and "not open to new users at this time"** per eBay's own filter reference. The old Finding API route (findCompletedItems/SoldItemsOnly) was decommissioned **Feb 5, 2025**.
- **Scraping ebay.com search pages is prohibited** by robots.txt and the API License Agreement; the API is the sanctioned path.
- Biggest architectural risk: sold-price data (needed for fair-price computation) is gated behind partner approval that eBay is currently not granting to new applicants. Plan a fallback (live asking prices as weak signal, or third-party sold-data vendors — §7).

## 1. Official search API: Browse API

**Endpoint:** `GET https://api.ebay.com/buy/browse/v1/item_summary/search` (sandbox: `api.sandbox.ebay.com`) — [Browse API OAS spec](https://developer.ebay.com/develop/api/spec/browse_api.json), [search method](https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search)

### Query parameters (v1.20.4)

| Param | Notes |
|---|---|
| `q` | Keyword. Max 100 chars (truncated beyond). No `*` wildcard. Space-separated = **AND**; `(a, b)` comma-in-parens = **OR** |
| `category_ids` | One category per request (Browse). L1 category requires `q` too |
| `epid` | eBay product ID; cannot combine with `q` |
| `gtin` | UPC/EAN/ISBN; cannot combine with `q` |
| `charity_ids` | US/UK only, ≤20 |
| `aspect_filter` | Item-specifics filter, e.g. `categoryId:179,Brand:{HP}`; category ID required **twice** |
| `compatibility_filter` | Vehicle fitment only — irrelevant to PCs |
| `fieldgroups` | `MATCHING_ITEMS` (default), `ASPECT_REFINEMENTS`, `BUYING_OPTION_REFINEMENTS`, `CATEGORY_REFINEMENTS`, `CONDITION_REFINEMENTS`, `EXTENDED`, `FULL` |
| `filter` | Field filters (below) |
| `sort` | `price`, `-price`, `distance`, `newlyListed`, `endingSoonest`; default Best Match; `distance` requires full pickup filter set |
| `limit`/`offset` | limit 1–200 (default 50); offset 0–9,999, must be multiple of limit; **hard cap 10,000 items per result set** |
| `auto_correct` | `KEYWORD` auto-correction (US + several EU sites) |
| Headers | `X-EBAY-C-MARKETPLACE-ID` (default `EBAY_US`), `X-EBAY-C-ENDUSERCTX` (affiliate IDs + `contextualLocation=country=US,zip=...`), `Accept-Language` |

### Field filters (`filter=`)

From [Buy API Field Filters](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html): `price:[10..50]` (must pair with `priceCurrency:USD`), `conditionIds:{1000|3000}`, `conditions:{NEW|USED}`, `buyingOptions:{FIXED_PRICE|AUCTION|BEST_OFFER|CLASSIFIED_AD}`, `itemLocationCountry`, `itemLocationRegion`, `deliveryCountry`, `deliveryPostalCode`, the four `pickup*` filters (§4), `maxDeliveryCost:0`, `paymentMethods:{CREDIT_CARD}`, `returnsAccepted:true`, `itemStartDate:[...]`/`itemEndDate:[...]` (ISO 8601 UTC), `sellers:{a|b}` (≤250), `excludeSellers`, `searchInDescription:true`, `sellerAccountTypes:{BUSINESS|INDIVIDUAL}` (EU only), `priorityListing:true`, `charityOnly:true`, `qualifiedPrograms:{...}`.

**Key default gotcha:** search returns **only listings with FIXED_PRICE (Buy It Now) as a buying option** by default; pure-auction listings require an explicit `buyingOptions:{AUCTION}` filter. ([search method description](https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search), [api-browse guide](https://developer.ebay.com/api-docs/buy/static/api-browse.html))

### Auth model

- **Application-only access token** via OAuth2 **client credentials grant** — no buyer authorization for search. Scope `https://api.ebay.com/oauth/api_scope` ("View public data from eBay"); verified in the spec's securitySchemes ([browse_api.json](https://developer.ebay.com/develop/api/spec/browse_api.json)).
- User-level OAuth (auth-code grant) only for checkout/bidding/identity operations ([Buy APIs Overview](https://developer.ebay.com/api-docs/buy/static/buy-overview.html)).
- Prereqs: eBay member account + Developers Program account ([join](https://developer.ebay.com/join/)) + app keyset ([Buy APIs Requirements](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html)).

## 2. Sold / completed listings data

- **Finding API — DEAD.** "All calls in the Finding API have been deprecated and will be decommissioned on **February 5, 2025**." ([findItemsAdvanced notice](https://developer.ebay.com/devzone/finding/CallRef/findItemsAdvanced.html))
- **Marketplace Insights API — official successor, gated.** `GET /buy/marketplace_insights/v1_beta/item_sales/search` returns listings "ended or completed in the **last 90 days**" ([OAS spec](https://developer.ebay.com/develop/api/spec/marketplace_insights_api.json)):
  - **Required:** `category_ids` (1–4; L1 also needs `q`/`gtin`/`epid`); partners are "given a list of categories they can use."
  - **Filters:** `conditionIds`, `conditions`, `itemLocationCountry`, `lastSoldDate:[range]`, `price`+`priceCurrency`, `aspect_filter`, `fieldgroups`, `sort` (price only), `limit` ≤200 / `offset` ≤9,999, 10k cap. `buyingOptions` NOT supported here.
  - **Response (`ItemSales`):** `lastSoldDate`, `lastSoldPrice`, `totalSoldQuantity`, `condition`/`conditionId`, `title`, `itemId`, `itemWebUrl`, `itemLocation` (postal+country), `categories`, `epid`, `seller`, images.
  - **Limitation:** sold records are **aggregated per item/product group** (last sale + total quantity in 90 days), not a per-transaction log. UNVERIFIED whether any official endpoint exposes individual per-sale prices/dates.
  - **Access:** Limited Release; the field-filters doc states verbatim: "**The Marketplace Insights API is restricted and not open to new users at this time.**" ([ref-buy-browse-filters.html](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html)). Scope `.../buy.marketplace.insights`; error 100017 = insufficient permissions. Community corroboration: [thread 1](https://community.ebay.com/t5/eBay-APIs-Talk-to-your-fellow/Marketplace-Insights-API-access/td-p/34838736), [thread 2](https://community.ebay.com/forum/apis-feedback-comments-and-suggestions-57951/topic/ebay-marketplace-insights-api-7658)
- **Feed API** (bulk, not sold data): daily new-listing TSV_GZIP feeds per category, weekly bootstrap, hourly snapshot. Limited Release, same partner gate. [Buy APIs Overview](https://developer.ebay.com/api-docs/buy/static/buy-overview.html), [Feed API v1](https://developer.ebay.com/api-docs/buy/static/api-feed.html)

## 3. Rate limits & production access

From [API Call Limits](https://developer.ebay.com/develop/api/buy/api_call_limits):

| API | Default |
|---|---|
| Browse API (all methods) | **5,000 calls/day** |
| Feed Beta (item/item_group/item_priority) | 10,000/day |
| Feed v1 / item_snapshot | 75,000/day |
| Taxonomy, Catalog, Deal, Marketing, Trading, etc. | 5,000/day |
| Marketplace Insights | **Not in the default table — UNVERIFIED** (likely 5,000/day) |

- **Higher limits:** eBay **Application Growth Check** ([/grow/application-growth-check](https://developer.ebay.com/grow/application-growth-check)); real-world approved increase 5,000→50,000/day via support case: [community thread](https://community.ebay.com/forum/browse-57957/topic/approved-browse-api-rate-limit-increase-not-applied-how-to-escalate-486726)
- **Production access (Buy APIs):** Limited Release → apply via **eBay Partner Network**: EPN account → Buy API questionnaire ([partnernetwork.ebay.com/page/developer-questionnaire](https://partnernetwork.ebay.com/page/developer-questionnaire)) → EPN responds ~10 business days → Developer Support ticket (sandbox test instructions + EPN approval email) → sign contracts → production enabled. [Buy APIs Requirements](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html)
- **Cost:** No fee documented for Developers Program ("membership is free" — [Get started](https://developer.ebay.com/develop/guides/sell/get-started-with-ebay-apis)) or Buy API production. License agreement warns of possible certification costs ([API License Agreement](https://developer.ebay.com/join/api-license-agreement)). **UNVERIFIED:** any explicit dollar pricing tier — none published.
- OAuth token endpoint has separate rate limits ([oauth-rate-limits](https://developer.ebay.com/api-docs/static/oauth-rate-limits.html) — page returned 403 to scout; exact token TTL UNVERIFIED, cache app tokens ~2h per general eBay practice).

**Capacity math (inference):** 5,000 Browse calls/day ≈ one search every ~17 s sustained, e.g. 50 watches × 100 refreshes/day. Fine for MVP; Feed API is the scale path.

## 4. Local pickup filtering

Fully supported in Browse `search`/`searchByImage`. Must send **all five together** ([Buy API Field Filters](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html)):

```
filter=deliveryOptions:SELLER_ARRANGED_LOCAL_PICKUP,
       pickupCountry:US,
       pickupPostalCode:95125,
       pickupRadius:25,
       pickupRadiusUnit:mi
```

- `pickupRadiusUnit`: `mi`|`km`; missing any → error 12010 ([browse_api.json](https://developer.ebay.com/develop/api/spec/browse_api.json)).
- `sort=distance` also requires the pickup filters.
- `pickup*` filters cause `deliveryCountry`/`deliveryPostalCode` to be ignored.
- Marketplace Insights: `itemLocationCountry` only — **no radius filter** on sold data.

## 5. ToS / bot detection

- **robots.txt (v30.2_COM_August_2026):** "The use of robots or other automated means to access the eBay site without the express permission of eBay is strictly prohibited," with a narrow search-engine-indexing exception. Explicitly disallows search paths: `Disallow: /sch/`, `/sch/i.html?_nkw=`, `/sch/ajax`, and browse facets (`/b/*?*_nkw`, `*_sop=`, `*_stpos=`...). Adds an explicit anti-LLM clause: "Automated scraping, buy-for-me agents, LLM-driven bots, or any end-to-end flow that attempts to place orders without human review is strictly prohibited... Approved enterprise integrations must use our official API and comply with our API License Agreement." ([ebay.com/robots.txt](https://www.ebay.com/robots.txt))
- **API License Agreement** governs API use; violations → reduced access/termination ([agreement](https://developer.ebay.com/join/api-license-agreement)); [eBay User Agreement](https://www.ebay.com/help/policies/member-behaviour-policies/user-agreement?id=4259).
- **Conclusion:** API is unambiguously the sanctioned path; HTML scraping of search pages violates robots.txt + User Agreement. Bot-detection enforcement specifics (HUMAN/captcha behavior): UNVERIFIED, not officially documented.

## 6. Practical: categories & "HP Z440" quirks

- **Category 179 = PC Desktops & All-In-Ones** (Electronics → Computers/Tablets & Networking → Desktops & All-In-Ones → PC Desktops & All-In-Ones). Confirmed via live browse URLs: [/179 PC Desktops](https://www.ebay.com/b/PC-Desktops-All-In-One-Computers/179/bn_661752), [/179 Desktop Computers](https://www.ebay.com/b/Desktop-Computers/179/bn_7023324363)
- **HP Z440 has its own browse node:** [HP Z440 PC Desktops & All-In-One Computers /179/bn_88009297](https://www.ebay.com/b/HP-Z440-PC-Desktops-All-In-One-Computers/179/bn_88009297) — eBay catalog recognizes the model; exact **ePID UNVERIFIED** — fetch via Catalog API `product_summary/search?q=HP Z440` ([docs](https://developer.ebay.com/api-docs/buy/catalog/resources/product_summary/methods/search)). `epid` search = cleanest exact-match route.
- **Category discovery:** full list not published; use Taxonomy API (`getDefaultCategoryTreeId`, `getCategorySubtree`, `getCategorySuggestions`) or `fieldgroups=ASPECT_REFINEMENTS` → `dominantCategoryId`. [Categories for Buy APIs](https://developer.ebay.com/api-docs/buy/buy-categories.html)
- **Title vs item specifics:** `q` matches titles (descriptions with `searchInDescription:true`); item specifics = **aspects**, enumerated via `ASPECT_REFINEMENTS`, filtered via `aspect_filter`. Used-PC sellers often leave specifics incomplete → keyword search remains the workhorse. [api-browse guide](https://developer.ebay.com/api-docs/buy/static/api-browse.html)
- **Condition IDs** ([reference](https://developer.ebay.com/api-docs/sell/static/metadata/condition-id-values.html)): 1000 New, 1500 New other/open box, 2000 Certified Refurb, 2010/2020/2030 Excellent/Very Good/Good Refurb, 2500 Seller Refurb, 3000 Used/Pre-owned, 6000 Acceptable, 7000 For parts.
- **Keyword semantics gotcha:** Browse = space is AND, `(a,b)` is OR ([browse_api.json](https://developer.ebay.com/develop/api/spec/browse_api.json)); Marketplace Insights docs describe the **opposite** (space = OR, comma = AND) ([marketplace_insights_api.json](https://developer.ebay.com/develop/api/spec/marketplace_insights_api.json)) — don't copy query strings between the two.
- **10,000-item retrieval cap** per result set — narrow with category+price+condition instead of deep paging.

## 7. Implications for BoldTrader (inference)

1. **Watch search:** Browse API fits cleanly — `q="HP Z440"&category_ids=179&filter=conditionIds:{3000|2500|2030},pickup...&sort=newlyListed`, poll within 5k/day.
2. **Fair-price model:** official sold-data route (Marketplace Insights) is closed to new users. Options: (a) apply for EPN/Buy production anyway, (b) third-party sold-data vendors (sold-comps.com, soldgraph — commercial, unvetted), (c) bootstrap from live asking prices with a discount factor until sold data lands.
3. **Flip value:** same search machinery per component category; no bundle-aware API support — component identification is app-side.
4. **Feed API** = upgrade path for full-category ingestion (hourly snapshots), same partner gate.

## Sources

1. Browse API OAS spec v1.20.4 — https://developer.ebay.com/develop/api/spec/browse_api.json
2. Browse `item_summary/search` — https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
3. Buy API Field Filters — https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html
4. Marketplace Insights OAS spec — https://developer.ebay.com/develop/api/spec/marketplace_insights_api.json
5. Buy APIs Requirements — https://developer.ebay.com/api-docs/buy/static/buy-requirements.html
6. Buy APIs Overview — https://developer.ebay.com/api-docs/buy/static/buy-overview.html
7. Browse API guide — https://developer.ebay.com/api-docs/buy/static/api-browse.html
8. API Call Limits — https://developer.ebay.com/develop/api/buy/api_call_limits
9. Condition ID values — https://developer.ebay.com/api-docs/sell/static/metadata/condition-id-values.html
10. Finding API deprecation — https://developer.ebay.com/devzone/finding/CallRef/findItemsAdvanced.html
11. ebay.com robots.txt — https://www.ebay.com/robots.txt
12. API License Agreement — https://developer.ebay.com/join/api-license-agreement
13. eBay User Agreement — https://www.ebay.com/help/policies/member-behaviour-policies/user-agreement?id=4259
14. Categories for Buy APIs — https://developer.ebay.com/api-docs/buy/buy-categories.html
15. Catalog product search — https://developer.ebay.com/api-docs/buy/catalog/resources/product_summary/methods/search
16. eBay cat 179 browse — https://www.ebay.com/b/PC-Desktops-All-In-One-Computers/179/bn_661752
17. HP Z440 browse node — https://www.ebay.com/b/HP-Z440-PC-Desktops-All-In-One-Computers/179/bn_88009297
18. Get started with eBay APIs — https://developer.ebay.com/develop/guides/sell/get-started-with-ebay-apis
19. Community: Marketplace Insights access — https://community.ebay.com/t5/eBay-APIs-Talk-to-your-fellow/Marketplace-Insights-API-access/td-p/34838736
20. Community: Browse limit increase — https://community.ebay.com/forum/browse-57957/topic/approved-browse-api-rate-limit-increase-not-applied-how-to-escalate-486726
21. Feed API v1 — https://developer.ebay.com/api-docs/buy/static/api-feed.html
22. Third-party sold data (unvetted) — https://sold-comps.com/use-cases/developer-integration ; https://soldgraph.com/docs/compare/ebay-marketplace-insights-api
