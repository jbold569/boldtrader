# Development

## Ports

Dev servers bind ports in the **10000 range** (10000–10999). The 8000 range is
reserved for other services on this host, and binding there collides with them
(seen in the wild: "Address already in use" on :8000 from a lingering process).

BoldTrader dev server:

```bash
.venv/bin/python -m src.server --host 0.0.0.0 --port 10000
```

## Running

```bash
# one-time setup
.venv/bin/python -m src.db            # creates/migrates boldtrader.db
.venv/bin/python -m src.facebook_scraper login   # first FB session only

# serve
.venv/bin/python -m src.server --port 10000
```

The liveness sweep (labels sold/deleted listings "no longer available") is
kicked off the first time a board is opened (`/bargains/:id`, which polls
`GET /api/v1/searches/{id}/liveness`) and runs in a background thread.

## Model router

The webapp pins `qwen3.8-flash-next-w4b-q8-halogen-pair` for chat and
Enrichment (see `src/router.py`). The `-pair` profile is the BoldTrader-
specific container the router keeps loaded, serving both models from one
container. The old plain id (the `...-halogen` id without `-pair`) causes
a container swap mid-turn and stalls requests (ADR 0007; supersedes
ADR 0006 §2) — never name it in current code or config.
