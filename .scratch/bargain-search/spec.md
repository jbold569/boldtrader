# Bargain Search — Spec

Status: ready-for-agent
Date: 2026-10-23

## Summary

A chat-authored buying intent that fans out keyword searches across marketplaces, then enriches the surfaced listings with AI-extracted facts (product identity, condition, bundle contents) so the user sees a curated, annotated view instead of raw keyword matches. The enhanced view is the product; the raw keyword page remains as the control group.

Terminology is canonical in `GLOSSARY.md`: **Bargain Search**, **Enrichment**, **Deal Target** (avoid — use Bargain Search), **Authored description**, **Unidentified listing**.

## Flow

1. **Chat authors the Bargain Search.** User talks to the LLM (halogen flash-next) about what they want to buy. The LLM asks clarifying questions until it can state the product identity back to the user, then presents a draft: a human-readable summary line ("Core i5-8400 mini PCs, complete, ≤ $150"), the curated keyword query list, and any exclusions. The user confirms or edits. Confirmation creates the Bargain Search. The user trusts the LLM to translate the summary into keyword queries; the summary is the human-auditable artifact, not the query list.
2. **Fan-out.** All curated queries run across eBay, OfferUp, and Facebook Marketplace (paginated), merged, deduped by (marketplace, listing id). Tolerant of any single marketplace failing — a zero from FB is a note, not an error. Same tolerance pattern as existing `_search_all`.
3. **Triage (small model).** Every new listing gets a cheap pass: title + snippet judged against the Bargain Search's product identity → **match / not-match / unsure**. Not-matches stay in the pass-through view but never enter the enhanced view. Unsures stay visible with a "needs review" marker — never silently dropped.
4. **Enrichment (large model).** Listings marked match or unsure are queued for the big model. It reads the full listing text (detail fetch, see below) and extracts strict field values: resolved product (manufacturer / model / config), condition (from the fixed set), bundle contents (each extra a product), with per-field confidence. A field the model can't fill is `unknown`, rendered as "?" — never guessed. Low-confidence fields explicitly invite an authored description.
5. **Enhanced view.** Matches only by default, ✨ on enriched cards, "show all" toggle as the safety net, reject button on enriched cards. Reject feeds the Bargain Search's exclusion list ("not this: OptiPlex 3070"); the next triage pass respects it. Authored description always overrides AI enrichment.

## Bargain Search lifecycle

- Multiple concurrent Bargain Searches.
- One-shot in MVP with a manual **re-run** button. Scheduled auto-rerun (Watch behavior) is deferred.
- **Refinement mutates the existing Bargain Search with a version bump.** The user hops into the chat at any time; the LLM translates the new needs into new knob positions (queries, filters, target price). Old results stay tagged with the version that found them.
- Target price is a field on the Bargain Search, editable via chat or directly. It is an **optional filter**: the enhanced view shows all matches by default; the user turns on the price filter when they have a number in mind. `shortcut: MVP treats asking price as out-the-door price; upgrade when per-marketplace shipping/fee parsing is reliable.`

## Data model (SQLite, single file, stdlib sqlite3, no ORM)

- `bargain_searches`: id, summary, product_identity, target_price, queries (json), exclusions (json), version, status, created_at, updated_at
- `conversations`: bargain_search_id, role, content, created_at — full chat transcript, append-only
- `listings`: id (`marketplace:listing_id`), raw fields (json), first_seen_at
- `enrichments`: listing_id, product (json), condition, bundle (json), confidence (json), model, status (`pending` / `enriched` / `failed`), created_at
- `rejects`: bargain_search_id, listing_id, reason, created_at

Enrichment is keyed by listing, not by Bargain Search: intrinsic facts about a listing are cached once, forever. Relevance judgment is per (listing, Bargain Search) and is cheap to re-run. A new Bargain Search next month = fresh triage over cached listings, zero big-model re-calls for already-enriched ones.

## Model contract (boldhalo router)

- OpenAI-compatible `/v1/chat/completions`, model name passed per call. boldtrader does not care which model answers; boldhalo owns routing.
- **Chat + enrichment**: `qwen3.8-flash-next-w4b-q8-halogen-pair` (BoldTrader's pinned container, ADR 0007).
- **Triage**: `decider-0.8b` on the XDNA 2 NPU via halogen's `/classify` endpoint (zero GPU memory). Fallback if NPU path unavailable: CPU-only Qwen3-4B-class Q4_K_M.
- Enrichment output contract: fixed schema, short field values, explicit `unknown` per field. The schema is boldtrader's; the model fills slots and never shapes the record. A bad field degrades to "?" instead of breaking the parse.
- Full stack rationale, hardware facts, and verify-first list: `docs/research/local-models-ms-s1-max.md`. Port the requirements into boldhalo from there.

## Orchestration

No framework. The pipeline is linear (fan-out → triage → enrichment), single-machine, and resumability is already handled by status columns in SQLite: a plain worker loop that picks `pending` rows, calls the router, writes results, retries once on failure. Airflow is overkill; Celery/RQ/Dramatiq all require a Redis broker and worker supervision to solve problems we don't have yet (distributed scheduling, fan-out across machines, DAG dependencies). The queue *is* the database. Revisit only if we outgrow one worker or need cron-style scheduled re-runs — at that point Huey (SQLite-backed, no broker) is the lightest step up.

## New marketplace interface

`Marketplace` gains `fetch_detail(listing) -> ListingDetail`: full description text, images, shipping/fee fields where the marketplace exposes them. Per-marketplace implementation:

- eBay: public listing page, trivial.
- OfferUp: GraphQL detail query — verify anonymous access before committing.
- Facebook: via the existing Playwright path; best-effort.

If a marketplace's detail fetch is unreliable, its listings get small-model triage only and are marked "enrichment unavailable" — one marketplace never blocks the pipeline.

## UI

- **Bargain Search list page** (new home): one row per search — summary line, status (running 34/120 · complete), match count, last-run time. Click → enhanced view. "New bargain search" launches chat.
- **Enhanced view**: match-filtered cards with ✨ enrichment annotations, pending markers on un-enriched listings, show-all toggle, reject button per card, target-price filter.
- **Chat panel**: create and refine; transcript persisted with the search.
- **Raw keyword search**: the existing page, unchanged, linked from the header as the control group.

## Performance expectations (from research)

- Triage: ~500 listings under a minute on NPU.
- Enrichment: ~30–60 s per listing → a 100-listing Bargain Search fills over ~1–2 hours. This is by design: kick it off, hunt manually, check back as results stream in.
- Enrichment concurrency 1 so chat never queues behind a batch on the same GPU. Queue persisted; server restart resumes it. Failed enrichment retries once, then marks failed.

## MVP scope

**In:** chat authoring + confirmation, fan-out, NPU triage, big-model enrichment with detail fetch, enhanced view (filter, toggle, ✨, reject), target-price filter, SQLite persistence, re-run.

**Deferred:** fair-price / deal-threshold machinery and price-observation accumulation (ADR 0001/0004), auto-rerunning Watches, vision on listing photos, correction-feedback learning, per-marketplace out-the-door fee extraction.

## Verification

Before trusting the stack (order per research doc): halogen startup "host memory left" line → NPU/fabric-clock gate → decider accuracy vs a human-labeled sample of ~50 listings → concurrent NPU+GPU decode interference → sustained thermals. Then: enrichment JSON reliability on 20 real listings across the three marketplaces before wiring the full enhanced view.
