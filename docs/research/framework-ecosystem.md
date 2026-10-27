# AI Chat + Mobile UI Ecosystem Survey — React vs Vue vs Next.js
**Ticket #15 · researched 2026-10-26 · for the BoldTrader frontend migration map (#14)**

> Verification notes: version/license/date/download figures were pulled live from the npm registry and `npm search` JSON API (retrieved 2026-10-26/27). Downloads from `api.npmjs.org` returned a stale 2026-06-02→07-01 window (registry-side staleness); `npm search` monthly figures match and are used. Bundle sizes were **not** locally benchmarked; shadcn/Radix deep mobile audit, Vuetify 4 migration pain, and Element Plus mobile responsiveness were assessed from documentation posture, not hands-on testing.

## Scope & criteria

Candidate set is fixed: **React, Vue, Next.js**. Decision criteria, in priority order:
1. Ecosystem prior-art: rich AI chat UX (streaming token rendering, chat kits) + mobile-responsive UI kits
2. Long-term stability / low breaking-change churn (AI-agent-maintained codebase)
3. Build/toolchain simplicity beside a Python backend
4. Bundle lightness (tie-breaker only)

Decision-relevant background (established elsewhere, not re-verified here): BoldTrader is a local single-user app; Python `http.server` backend, SQLite; the frontend will be a JS SPA consuming a JSON API + SSE streams. No Node toolchain exists today. **All third-party chat computation stays in the Python backend** — the frontend only consumes streaming output.

---

## 1. React

### 1.1 AI chat UI prior art — **strongest of the three**

| Library | Version | Last publish | License | Monthly downloads | Backend coupling |
|---|---|---|---|---|---|
| Vercel AI SDK (`ai`) | 7.0.154 | 2026-10-26 | Apache-2.0 | ~66.5M | Protocol-based over SSE; backend-agnostic (docs explicitly cover Python/FastAPI) |
| `@ai-sdk/react` (useChat) | 4.0.158 | 2026-10-26 | Apache-2.0 | (ships with `ai`) | Client-side only; talks the UI Message Stream protocol to any HTTP endpoint |
| `streamdown` | 2.7.1 | 2026-10-19 | Apache-2.0 | ~16.4M | Zero backend coupling — pure streaming-markdown renderer (drop-in for react-markdown) |
| `@assistant-ui/react` | 0.15.31 | 2026-10-22 | MIT | ~5.5M | Custom `ChatModelAdapter` (plain fetch → your Python API) or `DataStream` runtime; official Python transport backend exists |
| `deep-chat` | 2.5.1 | 2026-08-27 | MIT | ~86k | Web Component; custom streaming endpoint via own simple protocol; framework-agnostic |
| `@chatui/core` (Alibaba ChatUI) | 3.9.0 | 2026-10-12 | MIT | ~8.8k | Mobile-first chat kit; low adoption; dev deps pinned to React 17 |

Sources: npm registry metadata per package (registry.npmjs.org/`<pkg>`/latest); AI SDK stream protocol: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol ; custom/Python backends: https://sdk.vercel.ai/docs/ai-sdk-ui/streaming-data (explicitly names "e.g. Python / FastAPI"); assistant-ui custom runtimes: https://www.assistant-ui.com/docs/runtimes/custom/overview ; assistant-ui Python transport: https://github.com/assistant-ui/assistant-ui/blob/main/python/assistant-transport-backend/README.md ; streamdown: https://streamdown.ai ; deep-chat connect: https://deepchat.dev/docs/connect .

Key facts for our architecture (Python SSE, no JS server):
- **AI SDK's `useChat` is not tied to Next.js.** The UI Message Stream protocol is plain SSE; `useChat` can point at a `POST /api/chat` served by Python. The AI SDK 5 announcement confirms SSE as the wire standard; Pydantic-AI even ships a `VercelAIAdapter.encode_stream()` that emits the protocol from Python (https://pydantic.dev/docs/ai/integrations/ui/vercel-ai).
- **assistant-ui works against custom backends without any Vercel runtime** — either implement one adapter method (LocalRuntime) or have the backend emit its data stream. Caveat: still `0.x`; has shipped breaking renames across minors (e.g. v0.11 migration: https://www.assistant-ui.com/docs/migrations/v0-11) but ships an `npx assistant-ui upgrade` codemod.
- **streamdown** is the single most reusable piece for our exact need (rendering streamed assistant markdown incrementally): 16.4M monthly downloads, Apache-2.0, peer deps React 18/19, no server assumptions.
- Note: `@deep-chat/react` and `@deep-chat/vue` wrapper packages returned 404 from the npm registry (checked 2026-10-26); only the core web-component `deep-chat` is published.
- `@chatui/core` is effectively dormant in adoption terms (8.8k/mo vs assistant-ui 5.5M) despite recent releases; not a serious candidate.

### 1.2 Mobile-responsive UI kits — mature, multiple maintained options

| Kit | Version | Last publish | License | Monthly dl | Mobile posture |
|---|---|---|---|---|---|
| MUI (`@mui/material`) | 9.5.0 | 2026-10-09 | MIT | ~42.2M | Mobile-responsive grid, Drawer, responsive `sx` props |
| Mantine (`@mantine/core`) | 9.7.4 | 2026-10-25 (per npm upload ts) | MIT | (see note) | Mobile-first responsive styles, `use-media-query` |
| shadcn (`shadcn` CLI / Radix-based components) | 4.22.1 | ~2026-10-18 (per npm upload ts) | MIT | — | Copy-in components, Tailwind-based responsive primitives; also ships an MCP server |

Sources: npm registry metadata; shadcn CLI: https://ui.shadcn.com ; MUI v9 announcement: https://mui.com/blog/introducing-mui-v9 .
MUI v9 explicitly continues the accessibility/mobile-alignment line of its 2026 release (v9 blog). shadcn's model (copy source into your repo) is unusually agent-friendly: no library-version drift inside your app code.

### 1.3 Stability / churn

- React 18 → 19 (stable **2024-12-05**, https://react.dev/blog/2024/12/05/react-19) carried a real but one-time breaking purge: removal of `propTypes`/`defaultProps` on function components, legacy context, `ReactDOM.render`/`hydrate`/`unmountComponentAtNode` (Upgrade Guide: https://react.dev/blog/2024-04-25/react-19-upgrade-guide).
- Since then: **two years on the same major** (19.2 → 19.3.1, Oct 2026), no new major churn announced. React is now 624.9M monthly downloads (npm search 2026-10-26). Official docs (react.dev) are comprehensive and consistently rated best-in-class.
- The churn risk in React-land is **not React core** but the fast-moving peripheral AI packages (AI SDK had a major v6→7 in 2026: Node 22 minimum, renames, removed options — https://ai-sdk.dev/docs/migration-guides/migration-guide-7-0 and https://vercel.com/changelog/ai-sdk-7 ). Mitigate by pinning versions and preferring the backend-agnostic pieces (streamdown, plain SSE) over framework-coupled helpers.

### 1.4 Toolchain beside Python

- Recommended shape (same for React or Vue): **Vite** (8.3.5, MIT, 2026-10-21, https://vite.dev). `npm run build` produces **pure static assets** in `dist/` — Python `http.server` serves them directly; zero Node runtime in production.
- Dev ergonomics: `server.proxy` is a first-class documented feature: `{'/api': 'http://localhost:10000'}` routes API + SSE calls to the Python backend from the Vite dev server (https://vite.dev/config/server-options#server-proxy). SSE streams pass through the proxy (http-proxy-3-based).
- React needs only `@vitejs/plugin-react`. Full toolchain = 1 config file + a `package.json`. No Python↔JS build interdependency beyond `npm run build` at release time.

---

## 2. Vue

### 2.1 AI chat UI prior art — real but thinner; no dominant chat kit

| Library | Version | Last publish | License | Monthly dl | Notes |
|---|---|---|---|---|---|
| `markstream-vue` | 2.0.21 | 2026-10-26 | MIT | ~63k | Streaming-markdown renderer built specifically for LLM/SSE token streams, Mermaid/KaTeX |
| `vue-stream-markdown` | 2.1.0 | 2026-10-09 | MIT | ~56k | Same niche: streaming markdown for LLM output |
| `vue-stick-to-bottom` | 1.0.1 | 2026-07-22 | MIT | ~29k | Chat auto-scroll utility (Vue port of the React utility) |
| `@nuxt/ui` | 4.12.0 | 2026-10-15 | MIT | ~1.76M | Nuxt-bound UI lib (Nuxt not in our candidate set — completeness only) |

Sources: npm search API (2026-10-26) and registry metadata. [INFERENCE from search coverage:] there is **no Vue equivalent of assistant-ui/AI SDK** with comparable scale, docs, or streaming-protocol tooling. The 2026 landscape confirms the chat-component arms race is happening in React; Vue's pieces are single-purpose renderers to be composed into a full chat UX by hand. Vercel's UI Message Stream protocol has no first-party Vue consumer; Pydantic-AI's adapter targets the React AI SDK (`@ai-sdk/react`) specifically. The "custom Python SSE backend" question is **yes for both ecosystems** (it's `fetch` + SSE parsing), but the React side ships far more of the 80%.

### 2.2 Mobile-responsive UI kits — arguably the strongest mobile story

| Kit | Version | Last publish | License | Monthly dl | Notes |
|---|---|---|---|---|---|
| Vuetify | 4.3.1 | 2026-10-26 | MIT | ~4.1M | Material Design 3, CSS layers; v4 stable landed Feb 2026 after a big v3→v4 breaking wave (https://vuetifyjs.com/en/blog/february-2026-update/, roadmap: https://vuetifyjs.com/vuetify/roadmap) |
| Element Plus | 2.14.7 | 2026-09-30 | MIT | ~2.8M | Desktop-oriented toolkit (own docs: "A Desktop UI Toolkit for Web" — https://element-plus.org), long semver-stable 2.x run |
| Naive UI | 2.45.3 | 2026-08-27 | MIT | ~613k | Complete, themable; single primary maintainer; release cadence slowed |
| Vant | 4.10.2 | 2026-08-31 | MIT | ~488k | Purpose-built mobile Vue kit, ~1KB avg component gzip (https://vant-ui.github.io/vant/) |

(antd-mobile 5.43.0, 2026-09-14, MIT, ~383k/mo, exists on the React side and is well-maintained — checked for completeness.)

### 2.3 Stability / churn — mixed record

- **Vue 2 → 3 was the traumatic break** (Vue 2 EOL 2023-12-31, no security patches since: https://v2.vuejs.org/eol ; announcement: https://blog.vuejs.org/posts/vue-2-eol). That churn is behind us; we'd start on 3.
- Vue 3.x itself has been **exemplary**: 3.5.x patches continuously to 3.5.44 (2026-10-13) with strict semver discipline. Core docs (vuejs.org) are excellent, with a dedicated LLM-oriented docs export.
- **Caution ahead:** Vue 3.6 (Vapor Mode) is still **pre-release** (v3.6.0-rc.11, 2026-10-10) with the bulk of changes vapor-scoped; a 3.6 major-transition wave is pending and component libs (Vuetify/Element/Naive) must each absorb it — [INFERENCE] a deferred-churn risk specific to choosing Vue in late 2026, especially Vuetify, which just broke its own API surface in the v3→v4 transition.

### 2.4 Toolchain beside Python

- Identical to React: Vite + `@vitejs/plugin-vue`, pure static `dist/` output, `server.proxy` to the Python port. Vite originated in Vue-land; SFC HMR is the smoothest single-framework experience in the industry.
- In production the Python server serves `dist/` static files — exactly the pattern this repo already uses for `src/templates/` static assets (STATIC_DIR serving per current-frontend-audit), so the ops model doesn't change.

---

## 3. Next.js

### 3.1 AI chat UI prior art — best-documented, worst fit here

Vercel AI SDK was *born* in Next.js tutorials, and AI SDK 7 (7.0.154, current) is the reference implementation of the chat protocol. But under our criteria, this prior art is **decoupled from Next**: every React chat library listed in §1.1 works identically in a plain Vite React SPA. Next.js adds nothing to the chat UX we need (inference happens in Python), while its server features (Route Handlers, Server Actions) are exactly the ones we cannot use — see §3.4. The AI SDK docs (which assume a Next/Node route handler) make the React-in-Vite path *slightly* less turnkey: you substitute `POST /api/chat` (Python SSE) for the Next route handler, which the AI SDK's transport API (`ChatTransport`, `streamProtocol: 'text' | 'data'`) explicitly supports (https://sdk.vercel.ai/docs/ai-sdk-ui/chatbot).

### 3.2 Mobile-responsive UI kits

Next-bound equivalents are the **same React kits** as §1.2 (MUI/Mantine/Radix/shadcn all support Next). No Next-specific mobile advantage exists; shadcn's registry explicitly supports Vite and React SPA templates, not just Next (https://ui.shadcn.com).

### 3.3 Stability / churn — **worst of the three by a wide margin**

Documented breaking-change record:
- **13 → 14**: `next export` CLI removed; replaced by `output: 'export'` (version-history table in https://nextjs.org/docs/app/guides/static-exports).
- **14 → 15**: async Request APIs — `cookies()`, `headers()`, `draftMode()`, `params`, `searchParams` all became `async` — a forced codebase-wide change (https://nextjs.org/blog/next-15.md ; https://nextjs.org/docs/app/guides/upgrading/version-15 ; codemod: https://nextjs.org/docs/messages/sync-dynamic-apis).
- **15 → 16** (Oct 2025): `middleware.ts` renamed to `proxy.ts`; Turbopack becomes the **only** bundler by default (webpack demoted); Cache Components rework; Node ≥ 20.9 required (engines in `next@16.4.3` metadata) (https://nextjs.org/blog/next-16 ; https://nextjs.org/docs/app/guides/upgrading/version-16).
- **Security record:** recurring CVEs through 2026 including middleware/proxy bypass issues, e.g. CVE-2026-64642 affecting App Router + Turbopack single-locale setups (https://www.cve.org/CVERecord?id=CVE-2026-64642), and a July 2026 security release covering high-severity Server Actions DoS + middleware/proxy issues (https://makerkit.dev/blog/tutorials/nextjs-16 — citing https://nextjs.org/blog/august-2026-security-release).
- Churn cadence: ~1 major/year, each with breaking changes, plus a moving docs surface (multiple docs restructures 2024→2026). For an **AI-agent-maintained codebase**, the highest-cost profile of the three.

### 3.4 Toolchain beside Python / `output: 'export'` limitations — **disqualifying for this deployment**

Official static-export docs (https://nextjs.org/docs/app/guides/static-exports, updated 2026-08-09) enumerate what `output: 'export'` **cannot use**:
- Dynamic routes with `dynamicParams: true` or without `generateStaticParams()`
- Route Handlers that rely on `Request` (only static `GET` with `force-static` survives)
- Cookies, Rewrites, Redirects, custom Headers
- Proxy / middleware (formerly `middleware.ts`)
- Incremental Static Regeneration, Draft Mode
- **Server Actions**
- Intercepting Routes
- **Image Optimization with the default loader** (custom loader or third-party image service required)

Practical consequences for BoldTrader: an SPA backed by a Python API uses none of Next's server layer anyway; configure `output: 'export'` and what you get is a Vite-style static build — with Next's churn exposure, a 192 MB unpacked dependency (`next@16.4.3` unpackedSize per npm), Node ≥ 20.9 requirement, `out/` instead of `dist/`, and every default tutorial that quietly assumes a Node server requiring translation. Dev-time proxy ergonomics that Vite solves with 4 lines of `server.proxy` require an external rewrite layer you own yourself in export mode (rewrites are banned).
`next dev` with `output: 'export'` errors on unsupported features, so friction surfaces immediately rather than silently (same guide).

---

## 4. Comparison table (weighted by our criteria)

| Criterion (priority) | React | Vue | Next.js |
|---|---|---|---|
| **1. AI chat prior art** | ★★★★★ — AI SDK (`ai` 7.0.154, Apache-2.0, backend-agnostic SSE), assistant-ui (MIT, custom runtime + Python transport), streamdown (Apache-2.0, 16.4M/mo), deep-chat (MIT). Deep, active, all work against Python SSE. | ★★★ — real but single-purpose: markstream-vue, vue-stream-markdown, vue-stick-to-bottom (all MIT); ~10–100× smaller download scale than the React equivalents; no full chat-kit of assistant-ui's class. | ★★★★ — same React prior art applies, but Next-specific advantages are *unused* under our architecture; AI SDK docs' Next-route-handler defaults become translation overhead. |
| **2. Stability / churn** | ★★★★ — core stable 2 yrs on v19 (19.3.1, 2026-10-14); one-time 18→19 purge in Dec 2024; peripheral packages churn (pin versions). | ★★★★½ — Vue 3.5.x semver-strict; **but** 3.6/Vapor pre-release pending = deferred component-lib churn; Vuetify just broke v3→v4. | ★ — breaking changes every major 13→14→15→16; middleware→proxy rename; async-request forced migration; multiple 2026 CVEs incl. proxy bypass. |
| **3. Toolchain beside Python** | ★★★★★ — Vite: static `dist/`, `server.proxy` to Python port incl. SSE; 1 config file; no Node runtime in prod. | ★★★★★ — identical (Vite originated here; SFC HMR best-in-class). | ★★ — must force `output:'export'`; loses middleware/rewrites/cookies/Server Actions/image-optimizer by design; Node ≥ 20.9; 192 MB dep. |
| **4. Bundle lightness (tiebreak)** | ★★★★ — React 19 core + Vite is lean; tree-shakeable kits. [Not benchmarked.] | ★★★★★ — smaller core output; [not benchmarked]. | ★★★ — RSC/Routing framework overhead ships even with `output:'export'`. |
| **Verdict** | **Best fit.** | Solid runner-up. | **Poor fit** for a Python-backed local SPA. |

## 5. Bottom line

**React + Vite + Python (JSON API + SSE), static `dist/` served by the existing Python server** satisfies all four criteria best:
1. The rich-AI-chat prior art is overwhelmingly React-side, and — critically — AI SDK's `useChat` / assistant-ui's custom runtime both consume a **plain SSE endpoint served by Python**; nothing in the React chat stack requires a Node server.
2. React core has been churn-free since 19.0; where churn exists (AI SDK majors), the mitigation is version pinning, which this repo already practices via `requirements.txt` discipline.
3. Vite beside `http.server` is a solved problem: proxy in dev, static files in prod, zero Node in the runtime path.
4. Vue is a legitimate runner-up (nearly identical toolchain; slightly leaner bundles; slightly *pending* churn from the 3.6/Vapor transition and the Vuetify v4 shock). Its decisive gap is chat-component depth where criterion #1 lives.
5. Next.js fails criteria 2 and 3: worst churn record measured, and its static-export mode strips out exactly the features that justify its existence — maximum risk of the three for minimum benefit in this deployment.

**Recommended adoption stack (input to ticket #18's ADR):** React 19 + Vite + TypeScript; `streamdown` for streaming markdown; plain `fetch`/SSE against the Python backend (AI SDK protocol *optional* — `useChat` only if we adopt its message format server-side); mobile UI kit: MUI v9 or Mantine v9 (Tailwind + shadcn if we want copy-in, agent-editable components over library-version coupling). Pin all third-party versions; upgrade on our schedule, not theirs.
