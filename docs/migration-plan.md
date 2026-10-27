# BoldTrader Frontend Migration Plan

Locked decision from wayfinder ticket [Lift-and-shift sequencing plan](https://github.com/jbold569/boldtrader/issues/19). Consumes [api-contract.md](api-contract.md) (#17), [frontend-architecture.md](frontend-architecture.md) (#20), [ADR 0009](adr/0009-react-vite-spa.md). Vocabulary per [GLOSSARY.md](../GLOSSARY.md).

## Strategy: build alongside, single cutover

The old Python-rendered app keeps running **untouched** through the entire build. The new SPA is built complete in `frontend/` against the live backend: `/api/v1/` endpoints are added *alongside* the old routes, never replacing them until the end. At one moment — **cutover (M8)** — the old HTML route handlers and all of `src/templates/` are deleted, and the Python process serves only the built SPA and `/api/v1`.

Why single cutover: at ~7k lines, single-user, a per-route strangler collides with the SPA's catch-all rule (the old HTML routes *are* non-`/api/` GETs) and doubles renderers per page without buying anything at this size. One flip keeps the rollback story trivial.

**No redirect shim** (user decision): old URLs (`/search?id=N`, `/liveness`, `/index.html`) are not mapped to new SPA URLs. They fall through to the SPA fallback like any unknown path. Bookmarks die at cutover; accepted.

## Prerequisite

Node 22+ on the dev machine — **currently absent**. Install before M2. Needed only for the Vite build/dev-server, never at runtime (ADR 0009).

## Increments

Each increment ships working software with an exit check. Do not start the next until the current one's check passes.

### M1 — Backend JSON API (Python only)

Implement `/api/v1/` in full per `docs/api-contract.md`: searches CRUD, results (server-side filter/sort/pagination), rejections / reenrichment / liveness sub-resources, marketplace search, `PATCH /listings/{id}`, chat sessions CRUD, chat-turn SSE (`POST /api/v1/chat/sessions/{id}/messages`), and the global `GET /api/v1/events` stream with `: ping` every 15 s. Purely additive: every existing route stays byte-identical in behavior.

**Exit check:** new contract tests (see Test strategy) pass; the existing 123-test suite still passes; the old app in the browser is unchanged.

### M2 — Walking skeleton (ADR 0009 lock-in demo)

`frontend/` as a Vite + React 19 + TypeScript project: React Router v7 stub routes, TanStack Query v5 `QueryClientProvider`, theme bootstrap. `frontend/src/api/`: a thin typed fetch wrapper over the v1 contract (this is the API client layer). `npm run build` emits `frontend/dist/`; Python serves `dist/` for all non-`/api/` GETs with SPA fallback, failing fast at startup if `dist/` is missing. Dev: Vite `server.proxy` forwards `/api/*` → `:10000`.

**Exit check (this is ADR 0009's own checklist):** (1) build succeeds; (2) Python serves `dist/` with fallback and `/api/*` still works on the same port; (3) one live chat turn streams SSE from the model router through the proxy to the browser — demonstrated, not asserted.

### M3 — Prototypes (HITL, map tickets)

Work all five HITL prototype tickets before the pages they inform: [Chat page UX (#21)](https://github.com/jbold569/boldtrader/issues/21), [Enhanced view interaction (#22)](https://github.com/jbold569/boldtrader/issues/22), [Side-tray navigation (#32)](https://github.com/jbold569/boldtrader/issues/32), [Search / advanced search form (#33)](https://github.com/jbold569/boldtrader/issues/33), and [Search result view look-and-feel (#34)](https://github.com/jbold569/boldtrader/issues/34). They settle look-and-feel and the `reasoning`-channel surface-vs-suppress policy that #20 deferred. They run in the shared Vite app at `prototypes/` on port 10050, fake data inline, no backend. All five are gated by the firewall task [Open LAN ports 10000-10099 (#31)](https://github.com/jbold569/boldtrader/issues/31) — do that first. Throwaway artifacts; nothing here is production code.

### M4 — Searches list (`/searches`)

Paginated list from `GET /api/v1/searches`; create modal over the list (`SearchForm` → `POST /api/v1/searches`); `search_complete` events invalidate the list query.

**Exit check:** create a Bargain Search from the UI and the list updates without a manual refresh.

### M5 — Search Results view (`/searches/:id`)

`ResultCard` grid with Sift verdict, Enrichment display, per-card actions (reject → `POST …/rejections`, author description → `PATCH /listings/{id}`, re-enrich → `POST …/reenrichment`); filter bar (verdict / max_price / availability / sort / page) synced to URL query params; liveness banner from `GET …/liveness` plus `liveness` event invalidation; edit modal (`PATCH /api/v1/searches/{id}`).

**Exit check:** a filter change round-trips through the URL (survives reload and back/forward); an enrichment arrival live-updates a card without reload.

### M6 — Ad-hoc Marketplace Search (`/find`)

Query form + `ListingCard` grid + `failed_marketplaces` banner. Params in URL per architecture.

**Exit check:** a `marketplace=all` search with one marketplace failing shows the banner and still renders items.

### M7 — Chat surface (`/`, `/chat/:id`)

Session sidebar (`GET /api/v1/chat/sessions`), conversation component with the turn-stream reducer (spec below), inline draft-confirm (a `draft` event renders the same `SearchForm` pre-filled → save = `POST /api/v1/searches`), stop/regenerate.

**Exit check:** a streamed turn containing a tool call renders correctly; a draft produced mid-conversation saves and the new search appears in `/searches`.

### M8 — Cutover

Delete: every old HTML branch in `do_GET`/`do_POST`, the whole of `src/templates/`, and the old HTML tests still standing. Python serves: `/api/v1/*`, static assets from `dist/`, SPA fallback. Update any dev-doc references to old routes.

**Exit check:** the core loop end-to-end on the new surface: chat → draft → confirm → results with filters → reject → re-enrich → liveness. Old URLs do nothing useful; nothing references a template.

## SSE turn reducer (client chat-turn state machine)

The wire format is the contract's; this spec is the client-side fold. Pure function `reduce(state, event) → state`, no I/O:

```
state = { messages: [], pending: { text, reasoning, toolCalls: [], draft: null } }
```

| Event | Fold |
|---|---|
| `token` | `pending.text += data.text` |
| `reasoning` | `pending.reasoning += data.text`; render in the reserved collapsible slot per the #21 surface/suppress policy |
| `tool_call` | push `{name, arguments, status: "running"}` → chip appears |
| `tool_result` | mark the matching running chip complete, show `data.chip` text |
| `draft` | `pending.draft = data`; render `SearchForm` pre-filled inline in the conversation |
| `turn_complete` | commit `pending` as the assistant message into `messages`; reset `pending`; invalidate the session list (title may change) |
| `error` | keep the user's typed text and current `pending`; show the error on the turn; regeneration allowed from this state |
| disconnect mid-turn | no replay protocol (contract): re-`GET /api/v1/chat/sessions/{id}` and render persisted state |

Invariant: `turn_complete` is the only commit point; everything before it is preview. If the stream dies, the DB already holds the user message — the re-GET converges.

## Test strategy

1. **Contract tests (durable).** pytest, added with M1: every `/api/v1/` endpoint asserted against `docs/api-contract.md` — response shapes, pagination envelope, error bodies, SSE frame framing. This replaces the old HTML tests as the backend's test surface.
2. **Old HTML tests.** Deleted in the same commit that deletes their subject (M8), not converted. They assert HTML that no longer exists.
3. **Frontend tests (minimal, local tool).** Vitest unit tests over the two non-trivial logic pieces: the turn reducer above (fed a recorded event sequence, no network) and the filter-param↔URL sync. Plus **one Playwright smoke** driving a chat stream in a real browser (M7 exit). No full component suite.

## Rollback

Any increment before M8: revert that commit; the old app was never touched, so it still runs. After M8: revert the cutover commit — old handlers, templates, and tests come back wholesale.
