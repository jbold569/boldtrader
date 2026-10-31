# BoldTrader JSON API Contract (v1)

Locked decision from wayfinder ticket [JSON API contract for the new frontend](https://github.com/jbold569/boldtrader/issues/17).
Fixed enough that backend JSON-endpoint work proceeds regardless of framework choice (ticket [Decision: framework + serving topology (ADR)](https://github.com/jbold569/boldtrader/issues/18)).

## Conventions

- **Base path:** `/api/v1/`. Same-origin, single port. Python also serves the built SPA; all non-`/api/` GETs fall through to the SPA shell (client-side routing).
- **Field naming:** `snake_case` everywhere — request bodies, response bodies, SSE payloads. Mirrors the DB, the Glossary, and Python. No conversion layer; JS reads `effective_price`, not `effectivePrice`.
- **Money:** JSON numbers (floats), USD.
- **Timestamps:** ISO 8601 strings (`"2026-10-26T14:03:11Z"`).
- **Errors:** every non-2xx response body is
  ```json
  {"error": {"code": "search_not_found", "message": "No bargain search with id 9"}}
  ```
  `code`: machine-readable snake_case. `message`: human-readable. Status codes: `400` malformed request, `404` missing resource, `422` validation failure, `500` unexpected. Errors are never rendered HTML.
- **Pagination:** every list response uses the envelope
  ```json
  {"items": [], "page": 1, "per_page": 50, "total": 137, "total_pages": 3}
  ```
  `page` default 1; `per_page` default 50, max 200. Offset semantics (`LIMIT/OFFSET`).
- **Filter/sort:** applied server-side *before* pagination, never client-side over one page.
- **CORS:** none, anywhere. Local single-user tool, no auth. In dev the JS dev-server proxies `/api/*` to the Python port so the browser sees one origin.
- **Versioning:** breaking changes bump to `/api/v2/`. Additive fields are not breaking.

## Resources

### Bargain Searches

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/searches` | Paginated list |
| POST | `/api/v1/searches` | Create from draft; kicks fan-out in background |
| GET | `/api/v1/searches/{id}` | Single search resource |
| PATCH | `/api/v1/searches/{id}` | Partial update; bumps `version`, kicks fan-out |
| DELETE | `/api/v1/searches/{id}` | 204 |

**Search resource:**

```json
{
  "id": 3,
  "summary": "HP Z440 workstations under $300",
  "product_identity": "HP Z440",
  "target_price": 300.0,
  "location": "Kenmore, WA",
  "queries": ["hp z440", "z440 workstation"],
  "exclusions": ["no monitor"],
  "version": 2,
  "status": "complete",
  "match_count": 42,
  "created_at": "2026-10-20T09:15:00Z",
  "updated_at": "2026-10-26T14:03:11Z"
}
```

`status` enum: `active` (created, not yet run) → `running` (fan-out in progress) → `enriching` (fan-out done, enrichment pending) → `complete`. List items omit `queries`/`exclusions` and carry only `id, summary, status, match_count, updated_at`.

**Create/update body** (the draft — same shape chat produces and the advanced form submits):

```json
{
  "summary": "...",
  "product_identity": "...",
  "queries": ["..."],
  "exclusions": ["..."],
  "target_price": 300.0,
  "location": "Kenmore, WA"
}
```

Validation failures → `422` / `invalid_draft`, with the failing detail in `message`. A draft is chat output, not a server-held resource: discarding a draft is a client-side no-op (replaces today's `/reject` on drafts — note that today's `/confirm` maps to `POST /api/v1/searches`).

Identity mapping (ticket #60): the draft's `product_identity` phrase resolves the search's Product Identity at creation. An identity whose `description` equals the phrase exactly is reused; otherwise a new identity row is seeded from the phrase with `synthesized_at` null. A phrase already in use never mints a second identity. The identity's living description is written from evidence at `search_complete`, not by the phrase.

### Search results (enhanced view)

`GET /api/v1/searches/{id}/results`

Query params (all optional, combinable):

| Param | Values | Default |
|---|---|---|
| `page`, `per_page` | pagination | `1`, `50` |
| `verdict` | comma list: `match`, `unsure`, `not_match`, or `all` | `match,unsure` |
| `max_price` | number, compared against `effective_price` (not the ask) | none |
| `availability` | `live`, `dead` | all |
| `sort` | `price_asc`, `price_desc`, `newest` | `newest` |

Envelope `items` are result cards:

```json
{
  "listing_id": "offup:1234",
  "title": "Gaming PC i7 32GB",
  "url": "https://...",
  "asking_price": 250.0,
  "marketplace": "offerup",
  "image_url": "https://...",
  "verdict": "match",
  "verdict_stale": false,
  "availability": "live",
  "authored_description": null,
  "enrichment": {
    "status": "enriched",
    "product": {
      "description": "Dell OptiPlex 3060, i5-8500/8GB/256GB SSD",
      "action": "match",
      "matched_id": 3,
      "confidence": "high"
    },
    "condition": "complete",
    "bundle": [
      {"description": "power cord", "confidence": "high"}
    ],
    "confidence": "high"
  },
  "shipping": 10.0,
  "effective_price": 260.0,
  "fair_price": 400.0,
  "margin_pct": 35.0,
  "n_observations": 12
}
```

`shipping`, `effective_price`, `fair_price`, `margin_pct`, `n_observations` are computed per ticket #56. `effective_price = asking_price + shipping − flip_value(bundle)`. `fair_price` is the median of the trailing-90-day `price_observations` for the listing's identity+condition; `n_observations` counts them. `fair_price` and `n_observations` are `null` when the listing carries no `product_identity_id` or fewer than 5 observations exist. `margin_pct = (fair_price − effective_price) / fair_price × 100`, `null` when either term is `null`. These fields also drive the `max_price` filter above (it filters effective price, never the raw ask).

`verdict_stale` is `true` when the card's `verdict` was judged against a Product Identity description that has since been rewritten (ticket #55, ADR 0012): the verdict predates the current description and no re-sift has run over it. It flips to `true` the moment the description changes, and back to `false` when the search is re-run and the listings are re-sifted against the fresh description. `enrichment.status` enum: `pending`, `enriched`, `failed`; `enrichment` is `null` when no Enrichment record exists. `product.action` enum: `match` (the listing resolved to the existing Product Identity named by `matched_id`), `mint` (a new Product Identity was created; `matched_id` is `null`), `unknown` (Unidentified — no identity was minted). `confidence` is the identity-resolution confidence (`high|medium|low|unknown`); a mint only persists at `high`, so `mint` and `confidence: "high"` always travel together. `bundle` entries are typed: each extra item carries its own `confidence`. Field names follow `GLOSSARY.md` (asking price = seller's posted price).

### Per-search actions

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/v1/searches/{id}/rejections` | `{"listing_id": "...", "reason": "..."}` → `201` |
| DELETE | `/api/v1/searches/{id}/rejections/{listing_id}` | → `200` updated search resource (ticket #56) |
| POST | `/api/v1/searches/{id}/reenrichment` | empty → `201 {"requeued": 12}` |
| POST | `/api/v1/searches/{id}/run` | empty → `202` search resource; re-kicks fan-out, no version bump (ticket #56) |
| GET | `/api/v1/searches/{id}/liveness` | → `{"done": true, "banner": "", "dead": []}` |

Rejections are scoped to the search (glossary: feeding the exclusion list for the next sift). Re-enrichment never overwrites existing Enrichment (glossary definition). Liveness response keeps today's shape. The one-time re-enrichment wave for listings enriched before the Product Identity change: run this once per existing search (the endpoint re-queues only the missing/failed rows for that search's match/unsure listings, so it is safe to re-run):

```
curl -s -X POST http://localhost:10000/api/v1/searches/<ID>/reenrichment
```

### Product Identities

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/product-identities` | Paginated list |
| GET | `/api/v1/product-identities/{id}` | Single identity |
| PATCH | `/api/v1/product-identities/{id}` | Edit `description` and/or `deal_threshold` |
| POST | `/api/v1/product-identities/{id}/merge` | `{"into": <winner_id>}` → `200` winner |
| POST | `/api/v1/product-identities/{id}/retune` | Explicit synthesis → `200` identity |

**Identity resource:**

```json
{
  "id": 3,
  "description": "HP Z440 workstation, Xeon E5-1650 v2/16GB/512GB SSD",
  "deal_threshold": 35.0,
  "synthesized_at": "2026-10-26T14:03:11Z",
  "created_at": "2026-10-20T09:15:00Z",
  "updated_at": "2026-10-26T14:03:11Z"
}
```

`deal_threshold` is a percentage (`35.0` = margin ≥ 35% is a deal); `null` means fall back to the global `settings.deal_threshold`. `synthesized_at` is `null` until the description is model-synthesized (ADR 0012).

**PATCH** accepts a partial body: `{"description": "...", "deal_threshold": 30.0}` or `{"deal_threshold": null}` to clear the override. `description` must be non-empty; `deal_threshold` must be a positive number or `null`. Violations → `422` / `invalid_identity`. A hand-edit is not a synthesis: `synthesized_at` is untouched.

**Merge** (ticket #56): every listing, price observation, and search mapping pointing at the loser is re-pointed at the winner, then the loser is deleted — one transaction, all-or-nothing. Missing `into` → `400 / invalid_merge`; non-integer `into` or self-merge → `422 / invalid_merge`; unknown loser or winner → `404 / identity_not_found`; an error mid-transaction rolls back everything → `500 / merge_failed`. Response is the winner resource.

**Retune** is the explicit user-triggered version of the description synthesis (ADR 0012): evidence (matched listings, rejections, authored descriptions) is gathered from every search mapped to this identity and the model rewrites the description. On success `synthesized_at` is set and every mapped search's `stale_lids` is refreshed. A model/router failure → `500 / synthesis_failed`, nothing persisted. If the model returns blank or identical text the identity is returned unchanged (no-op).

### Deals

`GET /api/v1/deals` — the flat deal feed: every identified listing whose computed verdict is `deal`. No search context required.

Query params (all optional, combinable):

| Param | Values | Default |
|---|---|---|
| `page`, `per_page` | pagination | `1`, `50` |
| `sort` | `margin_desc`, `margin_asc` | `margin_desc` |
| `max_price` | number, compared against `effective_price` | none |
| `availability` | `live`, `dead` | all |
| `product_identity_id` | integer | all |
| `marketplace` | string, exact match | all |

Envelope `items`:

```json
{
  "listing_id": "offup:1234",
  "title": "HP Z440 Workstation",
  "url": "https://...",
  "asking_price": 120.0,
  "marketplace": "offerup",
  "image_url": "https://...",
  "condition": "complete",
  "shipping": 10.0,
  "fair_price": 200.0,
  "margin_pct": 35.0,
  "n_observations": 5
}
```

Only listings with a `product_identity_id` are considered, and only those the deal math calls a deal: `effective_price ≤ fair_price × (1 − threshold/100)`, where the threshold is the identity's override or the global `deal_threshold`. Listings in cold start (no fair price yet — fewer than 5 trailing-90-day observations) never appear: there is nothing to judge them against.

### Settings

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/settings` | → `{"deal_threshold": 25.0}` |
| PATCH | `/api/v1/settings` | `{"deal_threshold": 30}` → `200` full object |

`deal_threshold` is the global default deal margin percentage; a Product Identity's own `deal_threshold` overrides it. Values must be positive numbers; unknown keys → `422 / invalid_settings`. The response is always the full settings object.

### Enrichment correction

`PATCH /api/v1/enrichments/{listing_id}` — the Correction (GLOSSARY: a user-fixed fact that Enrichment never overwrites). Body carries at least one of:

```json
{
  "product_identity": "Dell Optiplex 7080 i5-10500/16GB",
  "condition": "complete",
  "bundle": [{"description": "mouse", "confidence": "high"}]
}
```

Only the fields you send are updated; the rest of the Enrichment record keeps its values. `product_identity` is a description string: if an identity with that exact description exists it is matched, otherwise a new one is minted (the listing's `product_identity_id` is repointed accordingly). `condition` must be one of the known condition values (or `"unknown"`); `bundle` items need a non-empty `description` and a `confidence` of `high|medium|low|unknown`. Violations → `422 / invalid_correction`; empty body → `400 / invalid_correction`; unknown listing → `404 / listing_not_found`.

Response `200`: `{listing_id, product, condition, bundle, corrected: true, status: "enriched"}` — the corrected record.

**Freeze semantics:** a corrected listing is frozen. Any later Enrichment pass (auto, fan-out, or re-enrichment wave) skips it and leaves the corrected fields alone. To re-open a listing to AI enrichment, issue a new Correction — there is no un-freeze endpoint in v1.

### Marketplace search (ad-hoc)

`GET /api/v1/marketplace/search?q=&marketplace=&location=&page=`

Paginated envelope of raw listing cards: `{id, title, url, asking_price, marketplace, image_url}`. `marketplace` default = server default; `all` fans across. Marketplace failures are reported, not fatal: response carries `"failed_marketplaces": ["facebook"]` alongside `items`.

### Listings

`PATCH /api/v1/listings/{id}` — `{"authored_description": "..."}` → `200` with `{id, authored_description, availability}`. Replaces `/describe`. Setting a non-empty authored description re-queues Enrichment for that listing (the authored description overrides Enrichment per glossary, so a re-enrichment follows).

### Chat Sessions

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/chat/sessions` | Paginated list: `{id, title, created_at, updated_at}` |
| POST | `/api/v1/chat/sessions` | `{"title": "..."}` (optional) → `201` session |
| GET | `/api/v1/chat/sessions/{id}` | `{id, title, messages: [{role, content, created_at}]}` |
| DELETE | `/api/v1/chat/sessions/{id}` | 204 |

**Chat turn (the streaming one):**

`POST /api/v1/chat/sessions/{id}/messages` — body `{"message": "..."}` → **SSE response** (`text/event-stream`), *not* a JSON result. The turn's events:

| Event | `data` |
|---|---|
| `token` | `{"text": "..."}` — assistant content delta |
| `reasoning` | `{"text": "..."}` — `reasoning_content` delta (surface policy is a UI decision, see map fog) |
| `tool_call` | `{"name": "...", "arguments": {...}}` |
| `tool_result` | `{"name": "...", "output": "...", "chip": "web search: \"hp z440\" — 12 results"}` |
| `draft` | the draft JSON object (same shape as create-search body) |
| `turn_complete` | `{"session_id": 3, "message": "final assistant text"}` |
| `error` | `{"code": "...", "message": "..."}` — model/router failure mid-turn; user message is already persisted |

Framing: `event: <name>\ndata: <json>\n\n`. These are **BoldTrader's own event names** — the OpenAI router format never leaks to the browser; the backend translates (router facts per ticket #16: `data:`-only frames, reasoning-before-content, tool-call deltas). The client reads the POST response with `fetch` + `ReadableStream` (EventSource can't POST). On disconnect the client reconnects by re-GETting the session; the turn's persistence is the DB, so no missed-state recovery protocol exists.

### Global events stream

`GET /api/v1/events` — long-lived SSE of background occurrences (enrichment arrivals, sweep progress, completions). Events:

| Event | `data` |
|---|---|
| `enrichment` | `{"listing_id": "...", "status": "enriched" \| "failed"}` |
| `liveness` | `{"search_id": 3, "done": false, "dead_count": 5, "banner": ""}` |
| `search_complete` | `{"search_id": 3, "match_count": 42}` |

`: ping` comment frame every 15 s to keep connections warm. Events are ephemeral: a reconnect starts from current state (all durable state lives in the DB; the stream is notification, not log).

## Not in contract v1

- **Watch** — glossary concept with no implementation behind it; inventing its shape now would be speculative API. Its contract addition ships with its own implementation.
- **Auth** — out of scope per map; the contract assumes the local trust boundary.
