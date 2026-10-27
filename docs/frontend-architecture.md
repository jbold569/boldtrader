# Frontend Architecture (React SPA)

Locked decision from wayfinder ticket [Component architecture for the React SPA](https://github.com/jbold569/boldtrader/issues/20). Sits inside the stack locked by [ADR 0009](adr/0009-react-vite-spa.md) and consumes the contract in [api-contract.md](api-contract.md). Vocabulary per [GLOSSARY.md](../GLOSSARY.md).

## Routes

| Route | Page | Backing API |
|---|---|---|
| `/` | Chat surface: session list sidebar + active conversation | `GET /chat/sessions` |
| `/chat/:id` | That Chat Session's conversation (deep link) | `GET /chat/sessions/{id}` |
| `/searches` | Bargain Search list | `GET /searches` |
| `/searches/:id` | Search Results view (filter bar, result cards, liveness banner) | `GET /searches/{id}`, `GET /searches/{id}/results` |
| `/find` | Ad-hoc Marketplace Search (ephemeral, no save) | `GET /marketplace/search` |

- **No `/new` or `/edit` routes.** Create = modal over `/searches` (`POST /searches`); edit = modal over `/searches/:id` (`PATCH /searches/{id}`). REST verbs double up on the noun; the page for a noun is also the place you mutate that noun.
- `/` is chat, not a dashboard — Chat Session is the primary surface (ADR 0008).
- `/find` stays separate from `/searches`: the glossary keeps an ephemeral **Search** apart from a durable **Bargain Search**; different resources, different pages.
- Today's standalone `/liveness` page is retired: liveness is a per-search sub-resource, its banner lives on `/searches/:id`.

## State strategy

- **TanStack Query v5 owns all server state.** Every GET is a query. Chosen over hand-rolled fetch because every list needs loading/error/pagination/keep-previous-page/refresh-on-change — that is re-implementing the library badly. One dependency (~11 KB gzip), stable.
- **Filters and pagination live in the URL query string** (`useSearchParams`), not component state. The contract already took them as query params; putting them in the URL makes the filter state survive reload and back/forward, and the params are the query key. Applies to `/searches/:id` results filters (`verdict`, `max_price`, `availability`, `sort`, `page`) and `/find` params (`q`, `marketplace`, `location`, `page`).
- **React-local state only for ephemeral UI**: open modals, dropdowns, in-progress form input.
- Query key convention: `['searches', {page}]`, `['search', id]`, `['results', searchId, filters]`, `['find', params]`, `['chat', id]`. Filters/params objects go straight into the key — key equality is URL equality.

## SSE fan-out

One `EventSource` on `GET /api/v1/events`, mounted in a provider at the app root, above the router. **No component ever opens its own connection.** The stream is notification-only (per contract), so fan-out = cache invalidation:

| Event | Invalidates |
|---|---|
| `enrichment {listing_id}` | all `['results']` queries (client doesn't know which searches display that listing; full-prefix invalidation is cheap locally) |
| `liveness {search_id}` | `['search', search_id]` and the liveness banner query |
| `search_complete {search_id}` | `['searches']` list, `['search', search_id]`, `['results', search_id]` |

EventSource auto-reconnects; `: ping` frames keep the connection warm. On reconnect, invalidate everything — durable state is the DB, so a full refetch converges.

The chat turn stream is **not** part of this fan-out: it arrives on the `POST /chat/sessions/{id}/messages` response body and is consumed by the conversation component via `fetch` + `ReadableStream` (EventSource can't POST).

## Component boundaries

Four shared components do most of the work; per-page copies are forbidden.

- **`ListingCard`** — a raw Marketplace listing: `id, title, url, asking_price, marketplace, image_url`. Used on `/find`.
- **`ResultCard`** — a listing within a Bargain Search's results: `ListingCard` content plus the Sift **verdict**, the **Enrichment** display, and per-card actions: reject (`POST /searches/{id}/rejections`), author description (`PATCH /listings/{id}`), re-enrich. Two components, not one with optional-props soup, because ad-hoc search payloads carry no verdict/enrichment.
- **Enrichment display** — a section of the `ResultCard`, not its own page: resolved product, condition, bundle, confidence. It's a first draft on the Listing (glossary); the **authored description** is edited inline on the same card, where the user sees what they're overriding.
- **`SearchForm`** — the draft fields (`summary, product_identity, queries, exclusions, target_price, location`), plain controlled inputs, no form library. Two mount points: the create/edit modals, and chat's draft-confirm flow (the `draft` SSE event renders this same form pre-filled; save → `POST /searches`).
- **Chat conversation** — the turn stream hook (`token` / `tool_call` / `tool_result` / `draft` deltas) lives in the conversation component. `reasoning` display has a reserved collapsible slot; **surface-vs-suppress policy is deferred to prototype #21**, not decided here.

## App shell

```
QueryClientProvider
└── EventsProvider          (single EventSource, invalidation table)
    └── RouterProvider
        ├── /            ChatSurface   (sidebar + Conversation)
        ├── /chat/:id    ChatSurface   (active session)
        ├── /searches    SearchList    (+ create modal: SearchForm)
        ├── /searches/:id SearchResults (filter bar + ResultCards + banner + edit modal)
        └── /find        Find          (query form + ListingCards)
```

## Dependencies

`react`, `react-dom`, `react-router` (v7, declarative library mode), `@tanstack/react-query`. Native `fetch` for requests — no axios. No form library, no state-management library beyond the above.

## Terminology note

"Enhanced view" (from the legacy `enhanced.html`) is informal speech for the Search Results view. It is not a term in the glossary and does not appear in this architecture.
