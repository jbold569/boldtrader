# BoldTrader

Finds deals on used computer hardware across online marketplaces. Scope is used goods only: secondhand, refurbished, for-parts, and damaged listings. New retail is out of scope.

## Language

**Deal**:
A listing whose effective price falls meaningfully below the fair price for that product in that condition.
_Avoid_: bargain (except in "Bargain Search"), steal, sale

**Flip value**:
The resale value of components included in a listing that the buyer does not need. Subtracted from the out-the-door price to get the effective price. A bundle of unwanted extras can turn an overpriced listing into a deal.
_Avoid_: salvage value, resale value (of the wanted item)

**Effective price**:
What the buyer really pays for the thing they want: out-the-door price minus the flip value of unwanted bundled components. The number deal math compares against fair price.
_Avoid_: net price, real cost

**Bundle**:
A single listing that includes multiple things — the wanted product plus extra components, each extra itself a Product with its own identity. Flip value applies to the unwanted extras.
_Avoid_: lot, package, set

**Fair price**:
An estimate of what a given product in a given condition typically goes for, derived from our own recorded price observations over time. Fair price is a function of both product and condition, never the product alone. It does not depend on any marketplace exposing sold history.
_Avoid_: market price, real price

**Price observation**:
A single recorded data point: the effective price seen for a product in a given condition on a given day. The pricing database is built by accumulating these observations over time.
_Avoid_: price point, data point

**Product**:
The canonical thing a listing is selling, identified by the app from the listing's own data (model numbers, specs), or by a user-authored description when the listing is too poorly described to parse automatically. Not from a user-maintained catalog. Price observations are pooled per product.
_Avoid_: item, SKU, catalog entry

**Unidentified listing**:
A listing the app cannot resolve to a product — typically vague titles, missing model numbers, poor photos. Surfaced in a separate bucket rather than dropped; these often hide the best deals precisely because they're poorly described. Resolved by a user-authored description (see Grandma search).
_Avoid_: unmatched, failed listing

**Grandma search**:
Searching with plain, layperson terms ("good computer", "CPU tower") rather than model numbers, to surface listings from sellers who don't know what they have. When such a listing is found, the user authors their own description from the listing photos and direct conversation with the seller.
_Avoid_: naive search, fuzzy search

**Authored description**:
A description the user writes for a listing based on what they see in the photos and learn from direct conversation with the seller. Used to resolve a poorly-described listing into a known product and condition.
_Avoid_: user note, manual description

**Condition**:
The state of the specific thing in a listing, drawn from a fixed set: complete, cosmetic damage, missing parts, for parts, refurbished. Condition changes the fair price; it is not merely a filter. Provenance varies by marketplace: eBay exposes structured condition IDs, Facebook exposes coarse used-grades, OfferUp exposes free text only on the detail record. Where structured values exist they map into the canonical set rather than passing through; where absent, condition is inferred from listing text or from the user's authored description. Neither provenance is fully trustworthy — sellers mislabel.
_Avoid_: state, grade, quality

**Refurbished**:
A condition: professionally restored and tested, typically with a warranty. Its fair price includes the value of that restoration and sits apart from plain complete.
_Avoid_: reconditioned, renewed

**Asking price**:
The price a seller posted on a listing. The number deal math uses for comparison. Negotiation is possible on every marketplace; on some it is expected and the ask runs systematically above the eventual transaction price, but the app treats the ask as the comparison number regardless.
_Avoid_: listed price, price

**Out-the-door price**:
What the buyer actually pays: asking price plus shipping plus any fees. The number deal math compares against fair price.
_Avoid_: total, sticker price

**Listing**:
One seller's posting of one thing on one marketplace. The atomic unit of supply.
_Avoid_: item, offer, posting

**Search**:
A keyword query submitted to a marketplace, returning a paginated set of Listings. Ephemeral by default — a Search becomes durable only when saved as a Watch.
_Avoid_: query, filter

**Watch**:
A saved search the user tracks. The app surfaces new listings matching a watch.
_Avoid_: alert, saved search, tracker

**Locality**:
The geographic scope of a watch: a center point and a radius. Local marketplaces are metro-scoped — a watch without a locality on a local marketplace sees nothing useful.
_Avoid_: area, region, location

**Deal threshold**:
How far below fair price a listing must fall to count as a deal, expressed as a percentage. A global default applies to every product; the user may override it per product. Market analysis may raise the threshold where a product's observed prices are noisy, but never lower it below the floor.
_Avoid_: cutoff, margin

**Price surge**:
A sustained rise in a product's market price driven by external events — new releases, component shortages, hype — rather than anything about individual listings. During a surge, listings priced at the surged level are not deals even if they look cheap against older memory.
_Avoid_: spike, inflation

**Wave**:
A burst of supply into the used market, typically triggered by corporate decommissioning cycles. Deals cluster in waves; between waves, supply thins.
_Avoid_: glut, flood

**Marketplace**:
A platform where listings appear — eBay, OfferUp, Facebook Marketplace, and similar. Marketplaces differ in what data they expose, their fee structures, whether they support bartering, and whether they offer a sanctioned API.
_Avoid_: platform, site, store

**For parts**:
A condition in which the thing is sold broken or incomplete, priced for salvage rather than use. Its fair price derives from salvage value, not from working comps.
_Avoid_: broken, junk, scrap

**ITAD** (IT Asset Disposition):
A business that acquires decommissioned enterprise equipment, wipes or destroys data, and resells it. A primary source of bulk used hardware.
_Avoid_: recycler, liquidator

**Enrichment**:
The AI-extracted facts added to a Listing beyond what the marketplace exposes: resolved product identity, normalized condition, and the bundle's contents as a list of additional products. Enrichment is a first draft — the user's authored description always overrides it.
_Avoid_: AI analysis, scoring, enhancement

**Bargain Search**:
A durable buying intent authored through a chat conversation with an LLM: the product(s) the user wants, plus a set of keyword queries the LLM curates and fans out across marketplaces. The broad net that feeds Enrichment; precise filtering happens after enrichment, not before.
_Avoid_: deal search, advanced search, broadcast
