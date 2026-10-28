# Frontend Architecture (React SPA)

Locked decision from wayfinder ticket [Component architecture for the React SPA](https://github.com/jbold569/boldtrader/issues/20). Sits inside the stack locked by [ADR 0009](adr/0009-react-vite-spa.md) and consumes the contract in [api-contract.md](api-contract.md). Vocabulary per [GLOSSARY.md](../GLOSSARY.md).

## Routes

| Route | Page | Backing API |
|---|---|---|
| `/` | Chat surface: session list sidebar + active conversation | `GET /chat/sessions` |
| `/chat/:id` | That Chat Session's conversation (deep link) | `GET /chat/sessions/{id}` |
| `/chat/sessions` | Chat Sessions list: all sessions + fuzzy search | `GET /chat/sessions` |
| `/bargains` | Bargain Search list | `GET /searches` |
| `/bargains/:id` | Search Results view (filter bar, result cards, liveness banner) | `GET /searches/{id}`, `GET /searches/{id}/results` |
| `/search` | Ad-hoc Marketplace Search (ephemeral, no save) | `GET /marketplace/search` |

- **No `/new` or `/edit` routes.** Create = modal over `/bargains` (`POST /searches`); edit = modal over `/bargains/:id` (`PATCH /searches/{id}`). REST verbs double up on the noun; the page for a noun is also the place you mutate that noun.
- `/` is chat, not a dashboard — Chat Session is the primary surface (ADR 0008).
- **Routes use the user's words, not the wire's** (nav labels, #32): `/search` = ad-hoc **Search**, `/bargains` = saved **Bargain Searches**, `/chat/sessions` = the Chat Sessions list. API paths keep the contract nouns (`/searches`, `/marketplace/search`); SPA route names and wire paths no longer mirror each other — deliberate (#35).
- Today's standalone `/liveness` page is retired: liveness is a per-search sub-resource, its banner lives on `/bargains/:id`.

## State strategy

- **TanStack Query v5 owns all server state.** Every GET is a query. Chosen over hand-rolled fetch because every list needs loading/error/pagination/keep-previous-page/refresh-on-change — that is re-implementing the library badly. One dependency (~11 KB gzip), stable.
- **Filters and pagination live in the URL query string** (`useSearchParams`), not component state. The contract already took them as query params; putting them in the URL makes the filter state survive reload and back/forward, and the params are the query key. Applies to `/bargains/:id` results filters (`verdict`, `max_price`, `availability`, `sort`, `page`) and `/search` params (`q`, `marketplace`, `location`, `page`).
- **React-local state only for ephemeral UI**: open modals, dropdowns, in-progress form input.
- Query key convention: `['bargains', {page}]`, `['bargain', id]`, `['results', searchId, filters]`, `['search', params]`, `['chat', id]`. Filters/params objects go straight into the key — key equality is URL equality.

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

- **`ListingCard`** — a raw Marketplace listing: `id, title, url, asking_price, marketplace, image_url`. Used on `/search`.
- **`ResultCard`** — a listing within a Bargain Search's results: `ListingCard` content plus the Sift **verdict**, the **Enrichment** display, and per-card actions: reject (`POST /searches/{id}/rejections`), author description (`PATCH /listings/{id}`), re-enrich. Two components, not one with optional-props soup, because ad-hoc search payloads carry no verdict/enrichment.
- **Enrichment display** — a section of the `ResultCard`, not its own page: resolved product, condition, bundle, confidence. It's a first draft on the Listing (glossary); the **authored description** is edited inline on the same card, where the user sees what they're overriding.
- **`SearchForm`** — the draft fields (`summary, product_identity, queries, exclusions, target_price, location`), plain controlled inputs, no form library. Two mount points: the create/edit modals, and chat's draft-confirm flow (the `draft` SSE event renders this same form pre-filled; save → `POST /searches`).
- **Chat conversation** — the turn stream hook (`token` / `tool_call` / `tool_result` / `draft` deltas) lives in the conversation component. `reasoning` display has a reserved collapsible slot; **surface-vs-suppress policy is deferred to prototype #21**, not decided here.

## App shell

```
QueryClientProvider
└── EventsProvider          (single EventSource, invalidation table)
    └── RouterProvider
        ├── /              ChatSurface     (sidebar + Conversation)
        ├── /chat/:id      ChatSurface     (active session)
        ├── /chat/sessions SessionsPage    (all sessions + fuzzy search)
        ├── /bargains      SearchList      (+ create modal: SearchForm)
        ├── /bargains/:id  SearchResults  (filter bar + ResultCards + banner + edit modal)
        └── /search        Search          (query form + ListingCards)
```

## Dependencies

`react`, `react-dom`, `react-router` (v7, declarative library mode), `@tanstack/react-query`. Native `fetch` for requests — no axios. No form library, no state-management library beyond the above.

## Terminology note

"Enhanced view" (from the legacy `enhanced.html`) is informal speech for the Search Results view. It is not a term in the glossary and does not appear in this architecture.

## Design tokens

Locked decision from wayfinder ticket [#36 Design-token set for the SPA (visual language)](https://github.com/jbold569/boldtrader/issues/36). This is the single source of truth for the SPA's visual values: the CSS at the end of this section is copied verbatim into `frontend/src/styles/tokens.css` and imported once at the app root. Page components use tokens only — no raw colors or px lengths.

### Color palette

Every color has two hand-authored values — one per theme — toggled by the `data-theme="light|dark"` attribute on `<html>`. Nothing is computed: no `color-mix()`, no runtime derivation. Changing a color means editing both blocks together.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f5f6f8` | `#101216` | page background |
| `--surface` | `#ffffff` | `#1a1d23` | cards, panels, inputs |
| `--surface-2` | `#eef0f4` | `#23272f` | nested surface, progress track |
| `--border` | `#dfe3ea` | `#2e333c` | default hairline |
| `--border-strong` | `#c4cad6` | `#444b57` | buttons, focused borders |
| `--fg` | `#1a1d23` | `#e6e8ec` | primary text |
| `--muted` | `#6b7280` | `#98a0ad` | secondary text |
| `--accent` | `#2563eb` | `#60a5fa` | primary actions, links |
| `--on-accent` | `#ffffff` | `#ffffff` | text on accent fills |
| `--ok` / `--ok-bg` | `#15803d` / `#e7f6ec` | `#4ade80` / `#12291c` | positive / match |
| `--warn` / `--warn-bg` | `#b45309` / `#fdf3e3` | `#fbbf24` / `#2b2312` | caution / unsure |
| `--bad` / `--bad-bg` | `#b91c1c` / `#fdeaea` | `#f87171` / `#2b1516` | error / negative |
| `--neutral-bg` | `#eceef1` | `#262a31` | neutral chips, no-verdict |
| `--scrim` | `rgba(0,0,0,.35)` | same | modal / tray backdrop |

The old prototype's `--error` / `--error-bg` were never defined (the dark error banner rendered with unset values); they are folded into `--bad` / `--bad-bg`.

### Spacing

A 4px scale. The prototype's 6/10/14 px drift is snapped up to 8/12/16; the jump is ≤2px and visually negligible at normal density.

`--space-1` 4 · `--space-2` 8 · `--space-3` 12 · `--space-4` 16 · `--space-5` 20 · `--space-6` 24 · `--space-7` 28 · `--space-8` 32 (px).

### Type

Five sizes, down from ten. `--text-xs` 12 · `--text-sm` 13 · `--text-base` 15 · `--text-lg` 18 · `--text-xl` 24 (px). Merges: 11→12, 12.5→13, 16/20→18. Line-height is set per component, not tokenized.

### Radius

`--radius-sm` 6px (buttons, inputs) · `--radius-md` 8px (cards, panels) · `--radius-pill` 99px (chips, confidence bars). Circular avatars stay `border-radius: 50%` — that's a shape, not a style value.

### Elevation

`--shadow-sm` cards · `--shadow-md` raised tray (upward) · `--shadow-lg` modal. The dark theme darkens `--shadow-sm` to compensate for the darker background; `--shadow-md`/`--shadow-lg` are pure-black overlays, identical in both themes.

### Verdict → tone

How a Sift verdict maps to a chip. Labels and the confidence threshold logic are functional values defined in `theme.tsx`, not CSS:

| Verdict (wire) | Chip label | Tone |
|---|---|---|
| `match` | MATCH | `--ok` on `--ok-bg` |
| `not_match` | NO | `--muted` on `--neutral-bg` |
| `unsure` | SURE? | `--warn` on `--warn-bg` |
| `pending` | SIFTING | `--accent` on `--surface-2` |

### Usage rule

- **Page components: tokens only.** No raw hex colors, no raw px for spacing, typography, or radius.
- **Exempt — the primitives own the micro values:** base element styles (`button`, `.chip`, `.card`, input base, hairline dividers) use raw `1px` and small px paddings directly. They are what the tokens are derived from.
- Raw values allowed nowhere else. Review checks this; mechanical enforcement (stylelint) is deferred until violations actually show up during M4–M7.

```css
/* BoldTrader SPA design tokens — single source of truth.
   Imported once at the app root. Page components use these only; no raw
   colors or px lengths. The dark theme is hand-authored value-for-value;
   never computed. Change a color = edit both [light] and [dark] blocks. */

:root,
[data-theme="light"] {
  /* palette */
  --bg: #f5f6f8;
  --surface: #ffffff;
  --surface-2: #eef0f4;
  --border: #dfe3ea;
  --border-strong: #c4cad6;
  --fg: #1a1d23;
  --muted: #6b7280;
  --accent: #2563eb;
  --on-accent: #ffffff;
  --ok: #15803d;
  --ok-bg: #e7f6ec;
  --warn: #b45309;
  --warn-bg: #fdf3e3;
  --bad: #b91c1c;
  --bad-bg: #fdeaea;
  --neutral-bg: #eceef1;
  --scrim: rgba(0, 0, 0, 0.35);
  /* elevation */
  --shadow-sm: 0 1px 3px rgba(20, 24, 32, 0.12);
  --shadow-md: 0 -2px 12px rgba(0, 0, 0, 0.25);
  --shadow-lg: 0 8px 30px rgba(0, 0, 0, 0.25);
}

[data-theme="dark"] {
  --bg: #101216;
  --surface: #1a1d23;
  --surface-2: #23272f;
  --border: #2e333c;
  --border-strong: #444b57;
  --fg: #e6e8ec;
  --muted: #98a0ad;
  --accent: #60a5fa;
  --on-accent: #ffffff;
  --ok: #4ade80;
  --ok-bg: #12291c;
  --warn: #fbbf24;
  --warn-bg: #2b2312;
  --bad: #f87171;
  --bad-bg: #2b1516;
  --neutral-bg: #262a31;
  --scrim: rgba(0, 0, 0, 0.35);
  --shadow-sm: 0 2px 6px rgba(0, 0, 0, 0.5);
  --shadow-md: 0 -2px 12px rgba(0, 0, 0, 0.25);
  --shadow-lg: 0 8px 30px rgba(0, 0, 0, 0.25);
}

/* Spacing: 4px steps (prototype drift 6/10/14 snapped to 8/12/16). */
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-7: 28px;
  --space-8: 32px;
}

/* Type: 5 sizes (was 10). Line-height stays per-component. */
:root {
  --text-xs: 12px;
  --text-sm: 13px;
  --text-base: 15px;
  --text-lg: 18px;
  --text-xl: 24px;
}

/* Radius: 3 values (was 7). 50% circles stay border-radius: 50%. */
:root {
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-pill: 99px;
}
```
