# 06 — Enhanced view

Status: ready-for-agent

Per Bargain Search: match-filtered card list. Enriched cards show ✨ + extracted fields (product, condition, bundle contents, confidence). Pending cards show "pending" marker. Failed show "enrichment failed". Show-all toggle. Optional target-price filter (off by default). Reject button on enriched cards → `rejects` row → next triage pass respects exclusions.

Authored description: user can write one on any card; it overrides AI enrichment everywhere downstream.

Verify: browse a completed Bargain Search; toggle filters; reject a card and confirm it disappears from matches and lands in exclusions.

## Comments

Built (2026-10-24):
- `src/enhanced.py`: the enhanced view. `view_cards()` assembles per-search card state (listing + enrichment + authored description), default = match/unsure only, `show_all` adds not-matches, rejected listings never appear, optional target-price filter (drops listings above target or with no price; off by default). `reject_listing()` writes the `rejects` row and appends the reason to the search's `exclusions` (deduped). `set_authored_description()` stores the user's text on the listing; the card renderer shows ✍ authored text instead of ✨ AI enrichment whenever it exists — the override.
- `src/templates/enhanced.html`: card list — ✨ + extracted fields (manufacturer/model/config/condition/bundle, each with per-field confidence, `?` for unknown), "needs review" on unsures, "⏳ pending" / "enrichment failed" markers, Reject button on enriched cards, per-card authored-description form, show-all toggle, target-price toggle, links to list page / chat / raw search.
- `src/templates/searches.html` + `list_searches()`/`render_searches_page()`: the Bargain Search list page (ticket 05 deferred the `running 34/120` rendering here) — summary, status, match count, last-run time, "New bargain search" link.
- `src/db.py`: `listing_ids` is now a JSON **dict** `{listing_id: verdict}` (was a list) so the view can mark unsures "needs review" and show not-matches under show-all; `listings` gains `authored_description`; `init_db` migrates both.
- `src/fanout.py`: `_persist_and_triage` returns the verdict dict and passes the search's exclusions into `router.triage`; fan-out writes the accumulated dict to `listing_ids`.
- `src/router.py`: `triage()` gains an optional `exclusions` param — "Never match these: …" appended to the system prompt.
- `src/chat.py`: `create_search` initializes `listing_ids='{}'` explicitly (old DBs' column default is `'[]'`, which would break `.items()`).
- `src/server.py`: `GET /search?id=N` (enhanced view, `&all=1` / `&price=1` toggles), `GET /searches` (list page), `POST /reject`, `POST /describe`.

Ran (Verify section, live against the real router, OfferUp, Dallas):
- Created Bargain Search #1 via `/confirm`; fan-out triaged 31 listings (4 match, 5 unsure, 22 not_match); enrichment worker drained 9/9 to `enriched`; status → `complete`.
- Browsed `/search?id=1`: ✨ fields on enriched cards, "needs review" on unsures, show-all toggle reveals the 22 not-matches, price filter ≤ $150 correctly drops the $999 listing.
- Rejected a card: it disappeared from matches, `rejects` row landed, `exclusions` now `["not this: OptiPlex 3050"]`, and the next fan-out pass feeds those exclusions into triage.
- Authored a description on a card: ✍ renders in place of ✨ AI enrichment; persisted on `listings.authored_description`.
- List page shows the search with status and match count; existing raw search page and chat page unaffected.
- Unit-level checks (temp DB): view filtering, show-all, price filter, reject→exclusions, authored override, render markers — all pass.

Notes:
- Reject reason auto-derives as "not this: <model>" from the enrichment (falls back to the title); the exclusion is plain text fed to the triage prompt, matching the spec's example.
- `shortcut: reject auto-derives the exclusion text; upgrade to an editable reason field if users want custom exclusions.`
