# Current Frontend Audit (2026-10-26)

Facts about the current BoldTrader web frontend, captured before any migration decision. Source: direct read of `src/` (see file refs).

## Summary
100% server-rendered HTML using Python `string.Template` (no Jinja2, no framework). JS is small vanilla ES5 (~100 lines `app.js` + ~45 lines `chat.js`) doing progressive enhancement only: theme toggle, drawer open/close, advanced-form toggle, markdown re-render of chat replies, and one polling loop. There is **no SSE, no WebSocket, no build step, no npm/node anything**. Every user action is a full-page HTML round-trip via plain GET/POST forms. The only "realtime" is a 4-second `fetch` poll of `/liveness` (JSON) that triggers at most one `location.reload()`.

## 1. Routes (`src/server.py`)
Raw `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`; no framework. Routing by exact `parsed.path` match in `do_GET`/`do_POST` (`src/server.py:347-511`).

### GET
| Route | Handler | Response |
|---|---|---|
| `*.{css,js}` | `_serve_static` (`server.py:822`) | Static files from `src/templates/` |
| `/chat`, `/chat?id=N` | `_handle_chat_get` (`server.py:518`) | HTML — session transcript |
| `/search?q=&loc=&m=&page=` | `_handle_raw_search` (`server.py:375`) | HTML — raw keyword results, TTL cache with stale-fallback |
| `/search?id=N` | `_handle_enhanced_get` (`server.py:637`) | HTML — enhanced card view |
| `/search?id=N&modify=1` | `_handle_modify_get` (`server.py:427`) | HTML — pre-filled advanced form |
| `/liveness?id=N` | `_handle_liveness_get` (`server.py:672`) | **JSON** — sweep status `{done, banner, dead:[...]}` |
| `/`, `/index.html`, `/searches` | `_handle_searches_get` (`server.py:682`) | HTML — Bargain Search list |
| anything else | — | 404 |

### POST (form-encoded; all return full HTML pages except one redirect)
| Route | Handler | Response |
|---|---|---|
| `/chat` | `_handle_chat_post` (`server.py:543`) | HTML — full re-render with new transcript + draft confirm forms |
| `/search` | `_handle_search_post` (`server.py:444`) | HTML — create/update Bargain Search, enhanced view |
| `/confirm` | `_handle_confirm_post` (`server.py:583`) | HTML — re-render chat; kicks `fan_out` thread |
| `/reject` | `_handle_reject_post` (`server.py:691`) | HTML — re-render enhanced page |
| `/describe` | `_handle_describe_post` (`server.py:723`) | HTML — re-render enhanced page |
| `/delete` | `_handle_delete_post` (`server.py:755`) | HTML — searches list |
| `/reenrich` | `_handle_reenrich_post` (`server.py:773`) | HTML — searches list |
| `/session/delete` | `_handle_session_delete_post` (`server.py:796`) | 303 redirect → `/chat?new=1` |

## 2. Templates (`src/templates/` — doubles as the static dir)
No `src/static/`; `STATIC_DIR = src/templates` (`server.py:36`). All templates are `string.Template` (`$var`) filled with Python-composed HTML strings; no templating logic in the HTML.

- **`index.html`** — raw search page: search bar (GET form), Advanced toggle, `$advanced` (Bargain Search authoring form), `$rows` (listing cards, `server.py:152`), `$pagination` (`server.py:120`).
- **`searches.html`** — drawer + banner + `$rows` list of Bargain Searches.
- **`enhanced.html`** — per-search card view: meta bar (`$summary/$count/$status`), `$toggles` (server-built filter links), `$rows` (enriched cards with reject forms / edit-description buttons), shared `<dialog>` posting to `/describe`.
- **`chat.html`** — `$transcript` (message bubbles + tool-result chips), `$confirm` (per-draft forms with hidden `remaining_drafts` JSON), say form carrying **hidden fields `transcript` (full session JSON) and `session_id`**, loading spinner overlay. Loads vendored `purify.min.js`, `marked.min.js`, `chat.js`, `app.js`.

## 3. `app.js` — vanilla, ~100 lines, four independent blocks
1. Theme toggle (`localStorage('bt-theme')`, `data-theme` attr, inline pre-paint snippet).
2. Drawer open/close/scrim/Esc + active-nav highlight (drawer HTML server-rendered by `chat.py:684`).
3. Advanced-form show/hide on `/search`.
4. Liveness poll on `/search?id=N`: `setInterval` 4s `fetch('/liveness?id=...')`; on change, one `location.reload()`.

## 4. `chat.js` — vanilla, ~45 lines
1. Re-renders each `.msg.assistant` bubble as markdown (`marked.parse` + `DOMPurify.sanitize`), sourcing text from the hidden `transcript` JSON field (never the DOM), skipping tool-call rows.
2. Submit → `#overlay` spinner until the full-page response replaces it.

Both are progressive enhancement: with JS off, the server-rendered escaped HTML remains functional.

## 5. Streaming / realtime
**None streaming.** Chat is request/response: `POST /chat` → `router.chat_with_tools` → blocking `requests.post` to the local model endpoint (`router.py:240`, non-stream JSON), multiple tool rounds possible (`chat.py:411-436`) → complete HTML page back. The user waits on a spinner. Single polling mechanism: liveness sweep poll (`/liveness` JSON, 4s). No `text/event-stream`, no WebSocket, no long-poll of model output.

## 6. State flow
- SQLite (`src/db.py`) holds all authoritative state: sessions, transcripts, bargain searches, enrichment, rejections, descriptions, liveness results.
- The frontend holds almost no state: theme in `localStorage`; the chat page smuggles full session `transcript` JSON through a hidden form field, and multi-draft confirm flows smuggle `remaining_drafts` JSON — client "state" is server-serialized state round-tripped through HTML forms. Every interaction = request → full HTML re-render from DB.
- Server-side in-memory state: search results TTL cache (`_Cache`, 15 min), liveness sweep state dict (`liveness.py` `_active`). Background daemon threads: `enrichment_worker`, per-request `fan_out` / `reenrich` / `liveness.start`.

## 7. Existing JSON API surface
Essentially one endpoint: `GET /liveness?id=N` → `{done, banner, dead}`. Everything else is HTML-in/HTML-out. An SPA needs the whole JSON API created, not just consumed.

## 8. Build tooling
None. No `package.json`, no node_modules, no vite/webpack/rollup config anywhere. JS assets hand-written and served as-is; `marked.min.js` and DOMPurify are vendored pre-minified files. Dev loop: `.venv/bin/python -m src.server --port 10000`.
