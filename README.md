# BoldTrader

Finds deals on used computer hardware across online marketplaces (eBay, OfferUp, Facebook Marketplace). Scope is used goods only: secondhand, refurbished, for-parts, and damaged listings. New retail is out of scope.

The core idea: a **deal** is a listing whose *effective price* (out-the-door price minus the *flip value* of unwanted bundled extras) falls meaningfully below *fair price* — an estimate built from our own accumulated *price observations*, per product and condition. No marketplace sold history required.

## Run

```bash
python -m venv .venv
.venv/bin/pip install requests beautifulsoup4 playwright
.venv/bin/playwright install chromium   # for OfferUp/Facebook scraping
.venv/bin/python -m src.server [--port 8000]
```

- Search UI: `http://localhost:8000/?q=dell+desktop&loc=Kenmore&m=all` (`m`: `all|offerup|facebook`)
- Bargain Search chat: `http://localhost:8000/chat` (refine an existing search: `/chat?id=N`)

State lives in `boldtrader.db` (SQLite, git-ignored). Local-only model inference; see `docs/adr/0006`.

## Layout

```
src/            Python app: server, routers, marketplace scrapers, enrichment
src/templates/  HTML templates
docs/adr/       Architecture decision records
docs/agents/    Agent skill configuration (issue tracker, triage, domain)
GLOSSARY.md     Domain vocabulary — the app's language; read before contributing
references/     Background research notes
.scratch/       Working scratch space
```

## Contributing

Issues are tracked in GitHub Issues via the `gh` CLI. Start with `GLOSSARY.md` — outputs use its vocabulary — and the ADRs in `docs/adr/` for the area you're touching.
