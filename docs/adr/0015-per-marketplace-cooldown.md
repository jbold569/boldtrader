# Per-marketplace cooldown instead of one global counter

The enrichment worker's outage detection counted consecutive failures globally: five failures from any source cooled down the whole queue. With three marketplaces of very different temperaments — eBay blocking under load, Facebook sessions expiring, OfferUp quietly anonymous — one dead platform throttles the live ones behind it. In the unattended daily sweep this converts a Facebook expiry into a lost morning across every marketplace.

We decided each marketplace keeps its own consecutive-failure counter and its own escalating cooldown (300 s doubling, capped at 3600 s, reset on its own success), and blocked rows for one marketplace never delay the others. This generalizes the per-marketplace access posture already recorded in ADR 0003: each marketplace is treated according to how its endpoint actually behaves, not as one blended firehose.
