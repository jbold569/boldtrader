# 04 — Bargain Search chat authoring

Status: ready-for-agent

Chat panel: user talks to flash-next, LLM clarifies until it can state product identity, then presents a draft Bargain Search (summary line, curated queries, exclusions, optional target price). User confirms or edits → row in `bargain_searches`, transcript in `conversations`.

- System prompt instructs the LLM: your job is translating the user's buying needs into keyword queries + filters; the summary line is the human-auditable artifact.
- Confirmation screen is the contract signing: show summary, queries, exclusions, target price; edit inline.
- Refinement: hop back into an existing search's chat → version bump, old results keep their version tag.

Verify: author one Bargain Search end-to-end; check DB rows; refine it; check version bump.
