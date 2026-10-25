# 0007. Pin all inference to the `-pair` profile; add search tools to the authoring chat

**Status:** accepted

Two coupled decisions. First: the boldhalo router now serves a BoldTrader-specific profile — a single container serving both of our models — under the id `qwen3.8-flash-next-w4b-q8-halogen-pair`. ADR 0006 §2 specified the plain id (`qwen3.8-flash-next-w4b-q8-halogen`) on the theory that swap-friendly routing mattered while testing new router profiles. That theory is void for BoldTrader: the plain id now causes a container swap mid-turn and stalls chat requests (observed live, 2026-10-25). **Boldtrader uses only the `-pair` id, for chat and for Enrichment. The old plain id must not appear anywhere in this app** — not in code, config, or current docs. Stored historical records that contain it (research documents, `enrichments.model` values) are history and stay untouched. This supersedes ADR 0006 §2's model-slot naming; 0006's local-only premise stands unchanged.

Second: the authoring chat gains two tools so the LLM can pull in context to identify the product the user wants, rather than guessing from the conversation alone. The tools are context-gathering mechanisms for product identification — not a general-purpose agent surface.

## Web search tool

Keyless DuckDuckGo via the `ddgs` Python package (`from ddgs import DDGS`), `backend="html"`, top 3 results per query, returning title / URL / snippet. No API key, no signup, no cloud inference (organic results only — we explicitly reject search engines that return an AI-synthesized "answer"; that would violate 0006's no-cloud-inference rule one layer deeper than retrieval).

Tradeoff, recorded plainly: this is an unofficial endpoint. Rate limits are opaque and DuckDuckGo can bot-gate us without notice. The tool degrades gracefully — on any failure it returns "web search unavailable" and the turn continues without web context. If gating becomes chronic, the swap to a keyed API (Tavily or Brave) is one function body.

`ddgs` note: the `duckduckgo-search` package (8.1.1, the last under that name) is deprecated and prints a rename warning on import; it also returned zero results on many queries in live testing. `ddgs` is the maintained continuation and was verified from this host (4/4 first-try, 1–2 s per query, html backend).

## Listing Store search tool

Keyword search over our persisted record of observed listings: `LIKE '%keyword%'` across the listing title and raw text, top 5 results. Each result carries the raw fields plus whatever Enrichment exists, with enrichment presence made **explicit** per hit (resolved product and condition when present; "not enriched" when absent) — the model needs the trust signal, not just text.

The persisted record has a canonical name: **Listing Store** (see `GLOSSARY.md`). It is not a Search: it queries what we already know, never a live Marketplace.

`LIKE` is deliberate, not lazy-by-accident: 608 rows / 0.31 MB scans in 0.2 ms. FTS5 was considered and rejected — its default tokenizer mangles exactly the strings we search most (hyphenated model numbers like `i5-8400`), and the speed benefit is imaginary at our scale. Revisit past ~50k listings or when keyword search shows up in a profile.

## Boundaries

- **Max 3 tool rounds per chat turn.** Beyond that the model is wandering, not clarifying.
- Every tool call renders in the chat as a one-line chip (e.g. `🔍 web: "rtx 4060 price" — 3 results`), so the user sees what the model looked up.
- **Tool output is persisted to the transcript.** It is session context the agent used, not user-visible prose. On revisit, the full tool history is restored to the model; the human sees chips, not raw dumps.
- The signed-draft contract is unchanged by tool use. Tools inform the draft; they do not alter its schema.

## UI

- **Spinner, not streaming.** On submit the page shows a JS spinner until the full-page response reloads. Streaming was considered (the router supports it) and deferred — the POST/reload architecture stays as-is for now; a spinner is the smallest honest signal.
- **Markdown renders client-side** with vendored `marked.min.js` + `DOMPurify.min.js` (static files served from `templates/`, no build step, no Python dependency). DOMPurify is mandatory: model output is untrusted HTML.
- **Thinking indicator is a CSS pulse only.** `reasoning_content` is never rendered — it is noisy, sometimes wrong, and invites trusting the garbage.

## Rejected alternatives

- **Tavily (keyed API)** — rejected for now: account, key management, and a paid dependency for a search we can get keyless. The failure mode (DDG gating) has a rehearsed escape.
- **Streaming output** — deferred, not rejected on the merits; it pairs with a richer "thinking" UX later.
- **FTS5 for the Listing Store** — rejected on tokenizer behavior and premature scale.
- **Rendering the model's reasoning** — rejected; noisy.
