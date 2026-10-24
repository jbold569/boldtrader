# 03 — boldhalo router client + enrichment schema

Status: ready-for-agent

`src/router.py`: thin OpenAI-compatible client for `http://model.boldhalo.home/v1/chat/completions`. Model name per call, timeouts, loud errors (retry once, then raise).

**Live-verified 2026-10-24**: chat completions works (flash-next, ~45 t/s decode, ~107 t/s prefill). `/classify` returns 404 — NPU triage not yet live on the router.

Two functions:
- `enrich(listing_text) -> dict`: calls flash-next with the fixed enrichment schema (product: manufacturer/model/config; condition from fixed set; bundle: list of items; per-field confidence or `unknown`). Low/no-thinking mode. Parse strict; a malformed response = failed enrichment, never a partial guess.
- `triage(listing_summary, product_identity) -> match|not_match|unsure`: interim implementation via chat completions with a small-model prompt until `/classify` is live; swap the body when it is, keep the signature.

Verify: enrich 5 real listings across marketplaces; print parsed records. Triage 10 listings; eyeball labels.

## Comments

Built (2026-10-24):
- `src/router.py`: thin OpenAI-compatible client for `http://model.boldhalo.home/v1/chat/completions` (stdlib + `requests`, already a dep). Model name per call, 120 s timeout, retry once then raise `RouterError`. `chat_template_kwargs: {enable_thinking: false}` for low/no-thinking mode (verified the router honors it).
- `enrich(listing_text) -> dict`: flash-next with the fixed schema (product: manufacturer/model/config; condition from the fixed set; bundle list; per-field confidence). Strict parse + schema validation: any violation raises `RouterError` — a failed enrichment, never a partial guess.
- `triage(listing_summary, product_identity) -> match|not_match|unsure`: interim chat-completions implementation with a one-word-label prompt. `decider-0.8b` is not on the router yet (`/v1/models` confirms; only flash-next is loaded), so the interim runs on the loaded chat model. Swap the body when `/classify` goes live; signature unchanged.

Ran: live verify against real listings — 5 enriched (OfferUp + Facebook; eBay 403 Akamai-blocked today, tolerated per the failure contract), 10 triaged.

Passed:
- 4/5 enrichments parsed clean with correct-shaped records (e.g. OptiPlex 7060 Micro → i7-8700/16GB, condition complete, high confidence).
- 1/5 failed strict parse: a multi-item lot got condition `"mixed"` — outside the fixed set → `RouterError`. That's the contract working as designed: no partial guess.
- Triage labels eyeballed sane: obvious matches → match, for-parts/lot/wrong-product → not_match, vague titles → unsure.

Notes:
- `TRIAGE_MODEL` currently aliases the enrich model; change it to `decider-0.8b` when the router loads it.
- The verify script was throwaway (per ticket-02 convention) and is not committed.
