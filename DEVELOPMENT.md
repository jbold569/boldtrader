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

The liveness sweep (labels sold/deleted listings "no longer available") starts
automatically when `/search?id=N` is opened and runs in a background thread.

## Model router

The webapp requests `qwen3.8-flash-next-w4b-q8-halogen` (plain id, see
`src/router.py`). NEVER use the `-pair` variant for the webapp: it pins a
fixed container, never triggers a profile change on the router, and deadlocks
container swaps while testing.
