# 04 — Bargain Search chat authoring

Status: ready-for-agent

Chat panel: user talks to flash-next, LLM clarifies until it can state product identity, then presents a draft Bargain Search (summary line, curated queries, exclusions, optional target price). User confirms or edits → row in `bargain_searches`, transcript in `conversations`.

- System prompt instructs the LLM: your job is translating the user's buying needs into keyword queries + filters; the summary line is the human-auditable artifact.
- Confirmation screen is the contract signing: show summary, queries, exclusions, target price; edit inline.
- Refinement: hop back into an existing search's chat → version bump, old results keep their version tag.

Verify: author one Bargain Search end-to-end; check DB rows; refine it; check version bump.

## Comments

Built (2026-10-24):
- `src/chat.py`: authoring core. `SYSTEM_PROMPT` (translate buying needs into keyword queries + filters; the summary line is the human-auditable artifact; short visible replies, draft carried in a fenced JSON block), `parse_reply` (splits reply text + draft; malformed draft = no draft, conversation continues), `validate_draft` / `draft_from_form` (strict contract: non-empty summary/product_identity/queries, exclusions list, positive-or-null target price), `next_reply` (one LLM turn), and the DB ops: `create_search`, `update_search` (version bump), `get_search`, `append_message`, `load_transcript`. Refinement turns get the current search state appended to the system prompt.
- `src/router.py`: added `CHAT_MODEL` + public `chat()` (2000-token cap; the authoring reply is longer than a triage/enrichment call).
- `src/server.py`: `/chat` (GET: empty for new search, DB transcript for `?id=N` refinement; POST: one authoring turn), `/confirm` (POST: contract signing — create, or refine with version bump; invalid form re-renders with the error flagged). DB initialized at server start.
- `src/templates/chat.html`: chat page with transcript bubbles, the inline-editable confirmation form, and the message box.

Ran: live end-to-end verify against the real router — authored one Bargain Search through chat (clarify → draft → confirm), checked `bargain_searches` + `conversations` rows, hopped back in via `/chat?id=1`, refined it, confirmed again.

Passed:
- Draft presented after identity settled; confirmation form rendered with the draft's values.
- Create: row #1 v1, queries/exclusions/target_price round-trip through JSON exactly; transcript persisted (user + assistant turns).
- Refine: v1 → v2, new queries/price persisted, refinement turns appended to `conversations`.
- Offline contract checks: malformed JSON draft, negative target price, empty queries all rejected; newline-separated form fields survive commas inside queries.
- Existing raw search page unaffected.

Notes:
- The model rambles past the token cap before the JSON block unless told to keep prose short; the prompt now forbids enumerating queries/exclusions as prose (the JSON carries them). Verified fixed.
- Transcript travels through the page in a hidden JSON field (stateless server, no session store).
