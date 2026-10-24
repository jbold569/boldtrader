# Prior-Art Landscape: BoldTrader (Used-Hardware Deal Finder)

Researched 2026-10-23. Open-source software overlapping BoldTrader's planned feature set. Cited throughout; UNVERIFIED items marked.

## (a) Project Table

|#|Project|URL|License|Last activity|What it does|Marketplaces|
|---|---|---|---|---|---|---|
|1|**PriceBuddy**|https://github.com/jez500/pricebuddy|GPL-3.0 **with non-commercial clause** (custom, NOT OSI)|Pushed 2026-10-11; 1.4k stars|Self-hosted price tracker: price history, deal scores, percentiles, seasonality, stock status, AI-assisted extraction, multi-user, CLI/MCP/browser extension|Any retail URL|
|2|**Discount-Bandit**|https://github.com/Cybrarist/Discount-Bandit|None declared|Pushed 2026-10-23; 755 stars|Multi-user self-hosted price tracker, criteria-based notifications|Amazon, AliExpress, eBay, Newegg, Walmart, Target, custom|
|3|**changedetection.io**|https://github.com/dgtlmoon/changedetection.io|Apache-2.0|Active (PyPI 0.55.8, 2026)|Generic web-page change/price-drop/restock monitoring with visual diff|Any URL|
|4|**PriceGhost**|https://github.com/clucraft/PriceGhost|None declared|1,131 stars; pushed 2026-02|Self-hosted price + stock monitoring|Any website|
|5|**PriceStalker**|https://github.com/mikeknight85/PriceStalker|MIT|Pushed 2026-10-13; 42 stars|Price tracking, multi-currency alerts, AI-assisted extraction, Docker|Any retailer|
|6|**ebay-price-monitor**|https://github.com/Igor-Kaminski/ebay-price-monitor|MIT|Created 2025-08|Watches eBay searches, alerts when listings undercut your price; Discord bot|eBay|
|7|**ebay-monitor** (samjmck)|https://github.com/samjmck/ebay-monitor|MIT|Last push 2023-9|Notifies when new eBay search results appear|eBay|
|8|**ebay-watch**|https://github.com/niski84/ebay-watch|MIT|Pushed 2026-06|Local eBay saved-search dashboard: Playwright + SQLite + web UI|eBay|
|9|**ebay_scanner**|https://github.com/Dusoye/ebay_scanner|None declared|Created 2025-04|Scans eBay listings, Discord alerts|eBay|
|10|**PricePulse eBay Tracker**|https://github.com/meritbh/PricePulse--eBay-Price-Tracker|None declared|UNVERIFIED|Scrapes eBay, email/SMS alerts on price drops|eBay|
|11|**pyOfferUp**|https://github.com/oscar0812/pyOfferUp|Other/NOASSERTION|Last push 2023-06|Python package scraping OfferUp search data|OfferUp|
|12|**Discord-Offer-Up-Webscraper**|https://github.com/sevivenegas/Discord-Offer-Up-Webscraper|None declared|Pushed 2026-04|Discord bot: scrapes OfferUp, daily market stats|OfferUp|
|13|**offerup-scraper** (data-scrape)|https://github.com/data-scrape/offerup-scraper|None declared|UNVERIFIED|Query → structured OfferUp data|OfferUp|
|14|**fb-marketplace-scraper** (tas33n)|https://github.com/tas33n/fb-marketplace-scraper|None declared|Pushed 2025-08|Monitors FB Marketplace keywords → Telegram + dashboard|FB Marketplace|
|15|**facebook-marketplace-watcher**|https://github.com/mania-rix/facebook-marketplace-watcher|Other/NOASSERTION|Pushed 2025-05|Headless Playwright login; emails recent listings|FB Marketplace|
|16|**facebook-marketplace-scraper** (danyk20)|https://github.com/danyk20/facebook-marketplace-scraper|MIT|Pushed 2026-10-05|FB Marketplace listing extraction|FB Marketplace|
|17|**ScrapedFace / facescrape**|https://github.com/rosesandhello/Facescrape|MIT (README)|UNVERIFIED date|FB Marketplace arbitrage scanner: AI product ID (llava vision + qwen2.5), defective/"for parts" detection, vague-lot filtering, pickup cost, SQLite history, twice-daily rechecks|FB Marketplace + eBay sold|
|18|**FlipRadar**|https://github.com/ericjimm44/flipradar|**None**|Pushed 2026-07-25, 3 commits|Browser PWA "seven-agent" pipeline: product ID from text, comp band scaling by condition, fee/ROI math, risk analysis, 0–100 ranking, threshold alerts, user comp book. Paste/JSON/demo input only — no scraping|eBay (via collector), paste for others|
|19|**Ebaymonitor** (BLABLA1000gg)|https://github.com/BLABLA1000gg/Ebaymonitor|**None declared**|Pushed 2026-06-13|Arbitrage monitor eBay/Kleinanzeigen/Vinted → buyback portals. AI condition assessment incl. vision, multilingual defect keyword blocking, per-storage-variant pricing, IQR+MAD outlier filtering, price history, deal score, blind-buy risk gating|eBay, Kleinanzeigen, Vinted|
|20|**flipper-app**|https://github.com/GTIstudios/flipper-app|MIT (README only)|Pushed 2025-11-27|Streamlit: scrapes Craigslist/FB, condition auto-parser, demand score, travel-cost model, recommended buy price|Craigslist, FB, eBay|
|21|**FlipFinder**|https://github.com/Joeflowcode/flipfinder|None declared|Pushed 2026-07-31|eBay deal scanner: underpriced vs sold comps, max-offer math, FB relist text; official eBay APIs|eBay|
|22|**Vinted Arbitrage Tool**|https://github.com/rjay-projects/Vinted-Arbitrage-Tool|MIT|UNVERIFIED|Vinted listings vs eBay sold prices, ROI filter, CSV|Vinted → eBay|
|23|**vinted-sniper**|https://github.com/jasp-nerd/vinted-sniper|MIT|Pushed 2026-10-11|Self-hosted saved-search monitor: new-listing alerts to Telegram/Discord/ntfy/RSS/webhook, 22 country sites|Vinted|
|24|**resell-tracker**|https://github.com/ArcherBullseye/resell-tracker|MIT|Pushed 2026-08-18|Umbrel retail arbitrage tracker: barcode lookup, eBay sold prices, buy/sell ledger, profit dashboard|eBay (retail sourcing)|
|25|**garage-radar**|https://github.com/tuckerrothmann/garage-radar|None declared|Pushed 2026-04-05|Classic-car market intel: raw snapshot store → per-source parsers → normalization (color/transmission/NLP flags) → comp clusters with median/P25/P75 → ask-vs-comp delta → UNDERPRICED/PRICE_DROP/RELIST alerts. Closest architectural template|BaT, C&B, PCarMarket, eBay|
|26|**hardwareswap-scrapper**|https://github.com/ojjc/hardwareswap-scrapper|None declared|UNVERIFIED (pre-"spez destroyed" era)|Keyword search of r/hardwareswap for PC deals|Reddit r/hardwareswap|
|27|**HardwareSwapNotifier**|https://github.com/Crowley2012/HardwareSwapNotifier|None declared|UNVERIFIED|Text/email when item posted on r/HardwareSwap|Reddit|
|28|**Reddit-Scraper** (joshuarreid)|https://github.com/joshuarreid/Reddit-Scraper|None declared|UNVERIFIED|Regex-parsed 72k r/hardwareswap posts into SQL DB|Reddit|
|29|**gpu-bot**|https://github.com/tomikonio/gpu-bot|None declared|UNVERIFIED|r/buildapcsales GPU deal monitor, 15-min polling, email|Reddit/Newegg|
|30|**gpu-price-tracker** (coreyjohnsen)|https://github.com/coreyjohnsen/gpu-price-tracker|None declared|UNVERIFIED|Newegg price scrape, email below threshold|Newegg|
|31|**gpu-deals** (HardwareDealsCo)|https://github.com/HardwareDealsCo/gpu-deals|Open dataset (UNVERIFIED)|Updated daily|Daily GPU deal dataset with $/frame metrics|Newegg et al.|
|32|**Ditto**|https://github.com/megagonlabs/ditto|Apache-2.0|Research code (WWW 2021, arXiv:2004.00584)|Deep entity matching with pre-trained LMs — canonical product ID from messy titles|General e-commerce|
|33|**catalog-forge**|https://github.com/alex-hahn/catalog-forge|UNVERIFIED|UNVERIFIED|Entity resolution + attribute extraction: product/variant/offer hierarchy, calibrated matching, benchmarks vs Splink/Dedupe|General|
|34|**keepa (Python wrapper)**|https://github.com/akaszynski/keepa|MIT (wrapper)|Active|Client for Keepa's commercial Amazon price-history API|Amazon (Keepa data)|
|35|**awesome-reseller-tools**|https://github.com/FLUF-io/awesome-reseller-tools|CC0-style|Maintained|Curated index of reseller tooling|Meta|
|36|**eBay Browse/Finding APIs**|https://developer.ebay.com/api-docs/buy/api-browse.html|Official API (not OSS)|Current|Keyword/category search, condition IDs, price filters|eBay|

## (b) Notable Project Notes

**PriceBuddy** — Most mature OSS price-history platform (1.4k stars, active Oct 2026). Records price history per tracked URL, computes deal scores, percentile distributions, drop events, seasonality; explicitly targets "fake discounts that aren't sales." Its insights DTOs (`DealScoreData`, `PercentileData`, `SeasonalityData`, `DistributionData`) are the closest OSS analog to BoldTrader's fair-price derivation — but it tracks **retail product pages by URL**, not used-goods listings by product+condition, and its license **prohibits commercial use** (custom GPL with non-commercial clause, [LICENSE.md](https://raw.githubusercontent.com/jez500/pricebuddy/main/LICENSE.md)). Do not vendor it.

**Ebaymonitor (BLABLA1000gg)** — Closest OSS to BoldTrader's condition-inference feature. Uses LLM text + vision to grade condition (functional state, battery, accessories, defects), hard-blocks multilingual "broken" keywords, treats eBay's "Für Ersatzteile oder defekt" as broken, prices per storage variant, applies IQR+MAD outlier filtering to sold prices before computing a conservative floor profit. Domain is phone flipping into German buyback portals, not PC hardware; no license declared; 2 stars. Good ideas to study, not to depend on.

**FlipRadar** — Conceptually the closest single-file blueprint of BoldTrader's deal pipeline: seven pure-function agents (deal finder → product identifier → market-value analyst → profit calculator → risk analyzer → ranker → alert gate), condition-scaled comp bands, max-offer bisection, user comp book that overrides built-in estimates. But it is a static browser app with seeded (hand-entered) comp data, no scraping of FB/OfferUp ("no legitimate automated path"), no daily observation database, no license, 3 commits. Treat as a design sketch that overlaps ~4 of 8 features, not a running system.

**garage-radar** — Best OSS **architecture template** for the non-eBay half of BoldTrader: raw-snapshot-first collection, per-source parsers, normalization layer (canonical colors/transmissions, NLP condition flags), dedup, Postgres schema (`listings`/`comps`/`comp_clusters`/`alerts`), and ask-vs-comp-delta alert rules (`UNDERPRICED: delta < -15% AND age < 3 days`). Niche = classic cars, and its fair value comes from *sold* auction data, not observed asking prices. No license declared.

**ScrapedFace (facescrape)** — Small but directly relevant: AI product identification from title→description→image (llava:13b + qwen2.5 via Ollama), explicit defective/"for parts"/"no core" detection, vague lot filtering, SQLite persistence, scheduled rechecks of tracked opportunities. MIT per README. Single-developer, thin.

**Commercial near-competitors (NOT open source, for landscape completeness):** Deal Scout (Grok bot watching eBay/FB/Mercari with price caps and deal-breakers, https://dealscoutbot.com/), ArbiSnap (FB Marketplace vs eBay sold, 40%-below flag, https://arbisnap.nanocorp.app/), HiveFB (own-machine FB Marketplace watcher, https://www.hivefb.app/), Swoopa (multi-marketplace private-party car sourcing, https://getswoopa.com/), UsedGamer (used PC parts cross-marketplace comparison, https://www.usedgamer.com/), PCPrice.watch (https://pcprice.watch/), HardwareHunter (https://hardwarehunter.io/), 1828couture (explicitly asks-price-based signals, https://1828couture.com/how-we-source/). None publish source.

## (c) Synthesis: Feature-by-Feature Prior Art

| BoldTrader feature | Prior art? | Best OSS coverage | Gap |
|---|---|---|---|
| 1. Watches (saved searches) | **Strong** | ebay-watch, vinted-sniper, samjmck/ebay-monitor, FB watchers | Commodity; nothing novel |
| 2. Product identification | **Partial** | Ditto (Apache-2.0, research-grade EM), catalog-forge, FlipRadar agent #2, Facescrape AI matcher | No maintained OSS tuned to used PC hardware (model-number extraction from noisy titles, SKU→canonical product mapping). Research code ≠ production library |
| 3. Condition inference | **Partial** | Ebaymonitor (LLM+vision grading, "for parts" blocking), Facescrape (defect keyword detection), flipper-app condition parser | No OSS with the full complete/cosmetic-damage/missing-parts/for-parts/refurbished taxonomy inferred from text; existing efforts are phone-centric or regex-only. eBay itself provides structured condition IDs (1000–3000) that solve this *on eBay only* |
| 4. Self-built price DB from observed asking prices per product+condition per day | **None found** | PriceBuddy records per-URL history (not per product+condition); garage-radar builds clusters but from *sold* data; 1828couture does asks-based signals but closed | **This is BoldTrader's clearest novel element.** Every OSS "fair value" tool leans on sold/completed data or hand-entered comps |
| 5. Flip value of unwanted bundled components (effective price) | **None found** | Only generic bundle-pricing calculators (seller-side, not buyer-side) | **Novel.** No OSS subtracts resale value of bundled extras to derive effective item price |
| 6. Deal detection (effective price < fair price − threshold) | **Strong** | garage-radar (ask-vs-comp delta), Vinted Deal Monitor (live-median discount), FlipFinder, FlipRadar alert agent | Mechanic is well-trodden; novelty is only that your "fair price" comes from your own DB (feature 4) |
| 7. Price-surge detection (market-wide rise vs true discount) | **None found in OSS** | Fake-discount detectors exist but detect per-item fake sales, not market-wide drift; academic work exists (structural-break CPI methods) | **Novel in this domain.** Requires the daily per-product+condition series from feature 4 to compute category-level drift |
| 8. Marketplaces: eBay / OfferUp / FB Marketplace | **Covered, unevenly** | eBay: official Browse/Finding APIs + many scrapers. OfferUp: pyOfferUp (stale 2023), assorted scrapers. FB: several Playwright scrapers, all fragile, all ToS-gray | OfferUp and FB coverage is thin, brittle, and ToS-risky; expect to build/maintain collectors yourself |

**Bottom line:**
- **No near-complete open-source competitor exists.** The closest OSS projects each cover 2–4 of the 8 features: FlipRadar (pipeline design, no data), Ebaymonitor (condition inference, wrong domain), PriceBuddy (history infra, wrong object + non-commercial license), garage-radar (architecture template, sold-data-based).
- **Novel/unserved core:** features 4, 5, and 7 — the self-built asking-price database per product+condition per day, bundle-component value subtraction, and market-surge-vs-discount discrimination — have **no open-source prior art**. Feature 6's math is common but is usually anchored to sold comps, which BoldTrader explicitly rejects.
- **Direct competitors are all closed-source SaaS** (Deal Scout, ArbiSnap, HiveFB, Swoopa, UsedGamer, HardwareHunter). The open-source field validates demand but leaves the specific combination BoldTrader plans unbuilt.
- **Reusable pieces:** eBay Browse API as the compliant eBay source; Ditto/catalog-forge for product matching; Ebaymonitor's condition-detection and outlier-filtering patterns; garage-radar's pipeline/schema design; changedetection.io patterns for snapshot-first collection.
- **License caution:** PriceBuddy's non-commercial clause makes it unusable in a commercial product; several closest projects (FlipRadar, Ebaymonitor, garage-radar, flipfinder) declare **no license at all**, meaning default copyright — study only, don't copy code.
