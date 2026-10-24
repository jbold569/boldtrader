# 03 — boldhalo router client + enrichment schema

Status: ready-for-agent

`src/router.py`: thin OpenAI-compatible client for `http://model.boldhalo.home/v1/chat/completions`. Model name per call, timeouts, loud errors (retry once, then raise).

**Live-verified 2026-10-24**: chat completions works (flash-next, ~45 t/s decode, ~107 t/s prefill). `/classify` returns 404 — NPU triage not yet live on the router.

Two functions:
- `enrich(listing_text) -> dict`: calls flash-next with the fixed enrichment schema (product: manufacturer/model/config; condition from fixed set; bundle: list of items; per-field confidence or `unknown`). Low/no-thinking mode. Parse strict; a malformed response = failed enrichment, never a partial guess.
- `triage(listing_summary, product_identity) -> match|not_match|unsure`: interim implementation via chat completions with a small-model prompt until `/classify` is live; swap the body when it is, keep the signature.

Verify: enrich 5 real listings across marketplaces; print parsed records. Triage 10 listings; eyeball labels.
