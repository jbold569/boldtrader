# Cross-marketplace fair price with per-marketplace adjustment

Status: superseded by ADR-0004 (self-built pricing database) and ADR-0001 (hybrid deal threshold). The data-source premise changed from marketplace sold data to our own recorded observations, and the per-marketplace adjustment concept itself was dropped — ask-based comparison needs no cross-marketplace normalization.

Fair price needs sold-price history, but the marketplaces we cover differ sharply in what they expose. eBay has rich completed-sale data. Facebook Marketplace has none — and it's a bartering marketplace where the listed price is an opening position, not a transaction price. GovDeals, Jawa.gg, and ITAD auctions each differ again. If we only used same-marketplace comps, Facebook listings would have no fair price and could never be flagged as deals.

We decided fair price is computed from **pooled sold history across marketplaces**, with a **per-marketplace adjustment factor** applied so that a Facebook ask is not judged against raw eBay comps. The adjustment accounts for the systematic differences: fee structures, buyer pools, and the bartering discount that local marketplaces carry. The bias is acknowledged and corrected rather than ignored.

Rejected: transferring eBay comps as-is (ignores real fee and buyer-pool differences, systematically misprices local listings), and same-marketplace-only comps (clean provenance but leaves bartering marketplaces with no fair price at all, killing deal detection there). The adjustment factor is itself derived from observed data where available, and falls back to a conservative default for a marketplace we haven't yet calibrated.
