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

### Search results (enhanced view)

`GET /api/v1/searches/{id}/results`

Query params (all optional, combinable):

| Param | Values | Default |
|---|---|---|
| `page`, `per_page` | pagination | `1`, `50` |
| `verdict` | comma list: `match`, `unsure`, `not_match`, or `all` | `match,unsure` |
| `max_price` | number | none |
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
  "availability": "live",
  "authored_description": null,
  "enrichment": {
    "status": "enriched",
    "product": {},
    "condition": "complete",
    "bundle": [],
    "confidence": {}
  }
}
```

`enrichment.status` enum: `pending`, `enriched`, `failed`; `enrichment` is `null` when no Enrichment record exists. Field names follow `GLOSSARY.md` (asking price = seller's posted price; `effective_price` is not carried on the card — it is deal-math, not stored data).

### Per-search actions

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/v1/searches/{id}/rejections` | `{"listing_id": "...", "reason": "..."}` → `201` |
| POST | `/api/v1/searches/{id}/reenrichment` | empty → `201 {"requeued": 12}` |
| GET | `/api/v1/searches/{id}/liveness` | → `{"done": true, "banner": "", "dead": []}` |

Rejections are scoped to the search (glossary: feeding the exclusion list for the next sift). Re-enrichment never overwrites existing Enrichment (glossary definition). Liveness response keeps today's shape.

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
