# 0008. General-purpose chat sessions; form-based Bargain Search creation

**Status:** accepted

**Supersedes:** 0007 §Boundaries (chat-as-narrow-authoring-surface); the per-search chat model (`/chat?id=<search_id>`); the `/raw` route.

Context: Bargain Search authoring was the only thing chat could do, and the enhanced/search pages were chained to it (every page linked "Refine in Chat"). ADR 0007 explicitly scoped the chat tools as "not a general-purpose agent surface." That constraint has now been lifted deliberately: the app becomes three pages — Home (saved Bargain Searches), Search, Chat — and chat becomes the general interface for research, analysis, and search management.

## Decisions

1. **Three pages.** `/` Home: the saved Bargain Search list (unchanged for now). `/search`: search page — raw marketplace search by default, an "Advanced" toggle reveals the bargain form; submitting it creates a Bargain Search and redirects to `/search?id=N`. `/chat`: the generic chat. `/chat?id=N` opens a specific Chat Session. `/raw` is removed.
2. **Chat Session is the unit of conversation, not the Bargain Search.** Sessions persist independently (`chat_sessions` + transcript rows keyed by session id). `/chat` resumes the most recent session; "New Chat" starts a fresh one. The session list (LLM-generated title from the first user message, newest first, last ~20) lives in the navigation drawer.
3. **The draft contract survives; its authorship splits.** The advanced form payload is the same contract `validate_draft` enforces. Agent-authored drafts still render the confirmation form for a human signing click before anything durable is created — in chat too. Creation is a form POST, not an LLM tool.
4. **Chat tool surface:** `search_listings`, `web_search` (both from 0007), plus `get_listing(id)` — full stored detail for one Listing, Listing Store only, never a live fetch — and `delete_bargain_search(id)`, usable only when the user has explicitly named the search to delete in their own message. Modification is the draft-confirm flow, not a direct tool.
5. **Tool-round budget raised 3 → 6.** The old cap assumed a narrow identification task; research turns legitimately chain lookups. The discipline is unchanged: the call after the cap is made without tools.
6. **The system prompt changes role.** "Search translator, not a purchase advisor" is replaced by: the agent may analyze and opine on deals within its data — state the math, flag fair-price confidence — but never invents facts beyond tool output and never urges the user to buy.
7. **Navigation moves to a side drawer** behind a hamburger icon, same behavior at every viewport width. No responsive dual-layout.
8. **Watch is untouched** — it remains a future, listing-specific "save for later" concept (see `GLOSSARY.md`), unrelated to Bargain Search.

## Consequences

- Existing per-search `conversations` rows become historical authoring records; new conversations live in `chat_sessions`. No migration.
- The enhanced view keeps its route (`/search?id=N`) but swaps "Refine in Chat" for a "Modify" affordance that deep-links the advanced form pre-filled.
- Searches can now be created without ever entering chat; chat can be used without ever creating one. The two are peers, not a pipeline.

## Rejected alternatives

- **Keeping chat search-scoped** (today's model): rejected — the user needs research and multi-search management that no single search owns.
- **Agent creates searches directly via tool** (no confirm form): rejected — durable data should not be written without a human click; N drafts in one session make silent creation worse.
- **`get_listing` live-fetching unfetched listings**: rejected — drags scraper rate limits into conversation latency; fan-out is the fetcher.
- **Fourth page for the session browser**: rejected — the drawer already exists; a `/chats` page contradicts the three-page scheme.
