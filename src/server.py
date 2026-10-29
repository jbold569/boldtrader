"""BoldTrader HTTP entry point: the JSON API plus the built SPA.

Run:  .venv/bin/python -m src.server --host 0.0.0.0 --port 10000
      (dev ports live in the 10000 range; see DEVELOPMENT.md)

Python serves three things and nothing else:
  /api/v1/*   -> the JSON API (src/api.py, docs/api-contract.md)
  real files  -> static assets from frontend/dist
  everything else -> frontend/dist/index.html (the SPA routes it client-side)

The legacy Python-rendered HTML layer was deleted at M8 cutover (ticket #51).
Old URLs are not redirected; they get the SPA shell like any unknown path.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import api
from .db import init_db
from .ebay_scraper import EbayScraper
from .facebook_scraper import FacebookScraper
from .fanout import enrichment_worker
from .marketplace import Marketplace, SearchResult
from .offerup_scraper import OfferupScraper


CACHE_TTL_SECONDS = 15 * 60

# Built SPA (ticket #43). Python hands out frontend/dist for every GET the API
# does not claim. The check runs before bind (ADR 0009: never silently start a
# server that cannot serve its own frontend).
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
DIST_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}


def check_frontend_dist(dist: Path) -> None:
    """Fail fast (before bind) if the SPA build is missing."""
    if not (dist / "index.html").is_file():
        raise SystemExit(
            f"frontend build missing: {dist / 'index.html'} not found. "
            "Run `cd frontend && npm install && npm run build` first."
        )


class _Cache:
    """In-memory TTL cache keyed on (marketplace, query, location, page)."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._store: dict[tuple, tuple[float, SearchResult]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple) -> SearchResult | None:
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            ts, value = hit
            if time.monotonic() - ts > self._ttl:
                return None
            return value

    def get_stale(self, key: tuple) -> SearchResult | None:
        """Return the cached value regardless of expiry, for error fallback."""
        with self._lock:
            hit = self._store.get(key)
            return hit[1] if hit else None

    def put(self, key: tuple, value: SearchResult) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), value)


class Handler(BaseHTTPRequestHandler):
    marketplaces: dict[str, Marketplace]
    fanout_marketplaces: dict[str, Marketplace]
    default_market: str
    cache: _Cache

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            api.handle(self)
            return
        self._serve_spa(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            api.handle(self)
            return
        self._not_found(parsed.path)

    def do_PATCH(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            api.handle(self)
            return
        self._not_found(parsed.path)

    do_DELETE = do_PATCH  # same dispatch: only /api/v1/ routes exist for these

    def _not_found(self, path: str) -> None:
        """Unrouted method+path: JSON, never HTML (contract: errors are not pages)."""
        self._send(
            404,
            json.dumps({"error": {"code": "not_found", "message": f"No route for {path}"}}),
            content_type="application/json",
        )

    def _send(self, status: int, body: str, content_type: str = "text/html") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_asset(self, f: Path) -> None:
        """Serve one file from frontend/dist (already resolved + guarded)."""
        data = f.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", DIST_TYPES.get(f.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(data)))
        immutable = str(f).find("/assets/") != -1
        self.send_header(
            "Cache-Control",
            "public, max-age=31536000, immutable" if immutable else "no-cache",
        )
        self.end_headers()
        self.wfile.write(data)

    def _serve_spa(self, path: str) -> None:
        """Serve a built SPA file; unknown paths get index.html (client routing)."""
        f = (FRONTEND_DIST / path.lstrip("/")).resolve()
        if f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            self._serve_asset(f)
            return
        self._send(200, (FRONTEND_DIST / "index.html").read_bytes().decode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # quieter default logging
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="BoldTrader server")
    parser.add_argument("--port", type=int, default=10000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--market", default="all", choices=["all", "offerup", "facebook"],
                        help="default marketplace; override per-request with &m=")
    args = parser.parse_args()
    check_frontend_dist(FRONTEND_DIST)  # fail before bind (ADR 0009)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db().close()
    Handler.marketplaces = {
        "offerup": OfferupScraper(),
        "facebook": FacebookScraper(),
    }
    Handler.fanout_marketplaces = {
        "ebay": EbayScraper(),
        "offerup": OfferupScraper(),
        "facebook": FacebookScraper(),
    }
    Handler.default_market = args.market
    Handler.cache = _Cache(CACHE_TTL_SECONDS)

    threading.Thread(
        target=enrichment_worker, args=(Handler.fanout_marketplaces,), daemon=True
    ).start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"BoldTrader serving on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
