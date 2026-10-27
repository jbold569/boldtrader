# Frontend stack: React 19 + Vite SPA

BoldTrader's new frontend is a plain React 19 SPA built with Vite (TypeScript), living in `frontend/` and consuming the `/api/v1/` JSON contract and SSE streams locked in ticket #17. Chosen because React carries the deepest AI-chat/streaming prior art of the three candidates, its core has been stable for two years (19.x since Dec 2024), and none of that prior art requires a Node server — every chat asset works against Python-served SSE. Full evidence: `docs/research/framework-ecosystem.md` (ticket #15), `docs/research/model-router-streaming.md` (ticket #16).

## Rejected options

- **Next.js**: worst breaking-change record of the three (13→14 `next export` removal, 14→15 async request APIs, 15→16 proxy rename/Turbopack-only, recurring 2026 CVEs). Its server features (Route Handlers, Server Actions) are unusable against a Python backend, and static export strips exactly the value it adds. The AI-chat prior art is decoupled from Next — it works identically in a Vite SPA.
- **Vue 3**: toolchain parity (same Vite story), but ~10–100× thinner AI-chat ecosystem — no assistant-ui/streamdown-scale tooling — plus a pending 3.6/Vapor churn wave that every component library must still absorb.
- **Plain JavaScript**: rejected in favor of TypeScript, whose type checker acts as a free contract test against the snake_case API surface; Vite's TS support is zero-config, so the "simplicity beside Python" criterion is unaffected.

## Served topology

- **Dev**: Vite dev server in `frontend/` with `server.proxy` forwarding `/api/*` to the Python backend (port 10000). HMR on the JS side; Python restarted as usual. The browser sees one origin — the contract mandates no CORS anywhere.
- **Production**: `npm run build` emits `frontend/dist/` with content-hashed filenames. The Python process serves `dist/` for all non-`/api/` GETs with SPA fallback to `index.html`. No Node runtime in production. `dist/` is gitignored — built assets are never committed; Python fails fast at startup if `dist/` is missing rather than silently invoking a build.
- Prerequisite: Node 22+ on the dev machine (currently absent). Needed only for the build/dev-server, never at runtime.

## Verification that this is actually locked

The decision is not locked until, in the first implementation slice after this map's prototypes: (1) `frontend/` exists as a Vite + React 19 + TypeScript project that builds to `frontend/dist/`; (2) the Python server serves the built `dist/` with SPA fallback and `/api/*` still works on the same port; (3) a dev-mode run reaches the browser through the Vite proxy and streams one SSE chat turn end-to-end from the model router. All three must be demonstrated, not asserted.
