# 01 — SQLite persistence layer

Status: ready-for-agent

Create `boldtrader.db` (single file, stdlib `sqlite3`, no ORM) with the tables from the spec:

- `bargain_searches`: id, summary, product_identity, target_price, queries (json), exclusions (json), version, status, created_at, updated_at
- `conversations`: bargain_search_id, role, content, created_at
- `listings`: id (`marketplace:listing_id`), raw (json), first_seen_at
- `enrichments`: listing_id, product (json), condition, bundle (json), confidence (json), model, status (`pending`/`enriched`/`failed`), created_at
- `rejects`: bargain_search_id, listing_id, reason, created_at

Plain schema-init function, idempotent (CREATE IF NOT EXISTS). DB path defaults to repo root, overridable via env. No query layer yet — just the schema and a connection helper.

Verify: init twice, inspect tables with sqlite3 CLI.
