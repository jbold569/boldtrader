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

## Comments

Built `src/db.py`: plain schema-init for the five spec tables (`bargain_searches`, `conversations`, `listings`, `enrichments`, `rejects`) plus a connection helper. stdlib `sqlite3` only, no ORM, no query layer.

- `db_path()`: resolves the DB file — `BOLDTRADER_DB` env override, defaults to `boldtrader.db` at the repo root.
- `get_connection(path=None)`: opens a connection with `PRAGMA foreign_keys = ON`.
- `init_db(path=None)`: `CREATE TABLE IF NOT EXISTS` for all tables (idempotent), returns an open connection.
- Added `boldtrader.db` to `.gitignore` so the runtime DB never lands in git.

Ran (Verify section):
- `init_db()` twice in a row — no error, idempotent confirmed.
- Inspected tables: all 5 present with the exact spec columns (`sqlite3` CLI is not installed on this machine; inspected via Python `sqlite3` + `sqlite_master` / `PRAGMA table_info` instead).
- FK enforcement check: inserting a `rejects` row with a nonexistent `bargain_search_id` raises `IntegrityError` through the helper connection.
- JSON column round-trip: `queries` stored as a JSON string, `json.loads` returns the list intact.

All passed.
