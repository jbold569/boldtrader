"""BoldTrader MVP: serve paginated marketplace search results on a local webpage.

Run:  .venv/bin/python -m src.server [--port 8000]
Search: /?q=dell+desktop&loc=Dallas&m=all   (m: all|offerup|facebook)
"""

from __future__ import annotations

import argparse
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .facebook_scraper import FacebookScraper
from .marketplace import Listing, Marketplace, SearchResult
from .offerup_scraper import OfferupScraper

CACHE_TTL_SECONDS = 15 * 60
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

_template = string.Template(TEMPLATE_PATH.read_text(encoding="utf-8"))


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


def _search_all(
    marketplaces: dict[str, Marketplace],
    query: str,
    page: int,
    location: str | None,
) -> tuple[SearchResult, dict[str, Exception]]:
    """Query every marketplace in parallel; merge listings, tolerate failures."""
    results: dict[str, SearchResult] = {}
    errors: dict[str, Exception] = {}

    def run(name: str, mp: Marketplace) -> None:
        try:
            results[name] = mp.search(query, page, location)
        except Exception as exc:
            errors[name] = exc

    threads = [threading.Thread(target=run, args=(n, m)) for n, m in marketplaces.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    merged: list[Listing] = []
    total = 0
    max_pages = 1
    for name, r in results.items():
        for l in r.listings:
            l.marketplace = name
        merged.extend(r.listings)
        total += r.total_results
        max_pages = max(max_pages, r.total_pages)
    return (
        SearchResult(
            listings=merged,
            total_results=total,
            page=page,
            page_size=max(1, len(merged)),
            total_pages=max_pages,
        ),
        errors,
    )


def _page_link(page: int, query: str, location: str, market: str) -> str:
    return f"/?q={quote(query)}&loc={quote(location)}&m={market}&page={page}"


def _render_pagination(page: int, total_pages: int, query: str, location: str, market: str) -> str:
    if total_pages <= 1:
        return ""
    parts: list[str] = []
    if page > 1:
        parts.append(f'<a href="{_page_link(page - 1, query, location, market)}">← Prev</a>')
    else:
        parts.append('<span class="disabled">← Prev</span>')

    start = max(1, page - 4)
    end = min(total_pages, page + 4)
    if start > 1:
        parts.append(f'<a href="{_page_link(1, query, location, market)}">1</a>')
        if start > 2:
            parts.append('<span class="disabled">…</span>')
    for p in range(start, end + 1):
        if p == page:
            parts.append(f'<span class="cur">{p}</span>')
        else:
            parts.append(f'<a href="{_page_link(p, query, location, market)}">{p}</a>')
    if end < total_pages:
        if end < total_pages - 1:
            parts.append('<span class="disabled">…</span>')
        parts.append(f'<a href="{_page_link(total_pages, query, location, market)}">{total_pages}</a>')

    if page < total_pages:
        parts.append(f'<a href="{_page_link(page + 1, query, location, market)}">Next →</a>')
    else:
        parts.append('<span class="disabled">Next →</span>')
    return "\n".join(parts)


def _render_rows(result: SearchResult) -> str:
    rows = []
    for l in result.listings:
        meta = ""
        if l.price is not None:
            meta += f'<div class="price">${l.price:,.2f}</div>'
        if l.condition:
            sold = f" · {l.sold_count:,} sold" if l.sold_count else ""
            meta += f'<div class="cond">{l.condition}{sold}</div>'
        snippet = f'<div class="snippet">{l.snippet}</div>' if l.snippet else ""
        img = f'<img src="{l.image_url}" alt="">' if l.image_url else ""
        badge = (
            f'<span class="badge badge-{l.marketplace}">{l.marketplace}</span>'
            if l.marketplace
            else ""
        )
        rows.append(
            f'<li class="card">{img}<div class="body">'
            f'<div class="titlerow">{badge}'
            f'<a class="title" href="{l.url}" target="_blank" rel="noopener">{l.title}</a></div>'
            f"{meta}{snippet}"
            f"</div></li>"
        )
    return "\n".join(rows) if rows else '<li class="card">No listings found.</li>'


def render_page(
    query: str,
    result: SearchResult,
    location: str = "",
    banner: str = "",
    source: str = "offerup",
) -> str:
    options = "".join(
        f'<option value="{m}"{" selected" if m == source else ""}>{label}</option>'
        for m, label in (("all", "All marketplaces"), ("offerup", "OfferUp"), ("facebook", "Facebook"))
    )
    return _template.substitute(
        query=query,
        location=location,
        banner=f'<div class="banner">{banner}</div>' if banner else "",
        total=f"{result.total_results:,}",
        page=result.page,
        total_pages=result.total_pages,
        source=source,
        market_select=f'<select name="m">{options}</select>',
        rows=_render_rows(result),
        pagination=_render_pagination(result.page, result.total_pages, query, location, source),
    )


class Handler(BaseHTTPRequestHandler):
    marketplaces: dict[str, Marketplace]
    default_market: str
    cache: _Cache

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            self._send(404, "Not found")
            return

        qs = parse_qs(parsed.query)
        query = (qs.get("q") or [""])[0].strip()
        if not query:
            query = "HP Z440"
        location = (qs.get("loc") or [""])[0].strip()
        market = (qs.get("m") or [self.default_market])[0].strip().lower()
        valid = set(self.marketplaces) | {"all"}
        if market not in valid:
            market = self.default_market
        try:
            page = max(1, int((qs.get("page") or ["1"])[0]))
        except ValueError:
            page = 1

        key = (market, query.lower(), location.lower(), page)
        cached = self.cache.get(key)
        if cached is not None:
            self._send(200, render_page(query, cached, location, source=market))
            return

        try:
            if market == "all":
                result, errors = _search_all(self.marketplaces, query, page, location)
                banner = ""
                if errors:
                    failed = ", ".join(f"{n} ({e.__class__.__name__})" for n, e in errors.items())
                    banner = f"Marketplace(s) unavailable: {failed}"
            else:
                result = self.marketplaces[market].search(query, page, location)
                banner = ""
        except Exception as exc:  # total failure: fall back to stale cache
            stale = self.cache.get_stale(key)
            if stale is not None:
                self._send(
                    200,
                    render_page(
                        query,
                        stale,
                        location,
                        banner=f"Live fetch failed ({exc.__class__.__name__}); showing cached results.",
                        source=market,
                    ),
                )
            else:
                self._send(502, f"Search failed and no cached results: {exc}")
            return

        self.cache.put(key, result)
        self._send(200, render_page(query, result, location, banner=banner, source=market))

    def _send(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # quieter default logging
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="BoldTrader MVP server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--market", default="all", choices=["all", "offerup", "facebook"],
                        help="default marketplace; override per-request with &m=")
    args = parser.parse_args()

    Handler.marketplaces = {
        "offerup": OfferupScraper(),
        "facebook": FacebookScraper(),
    }
    Handler.default_market = args.market
    Handler.cache = _Cache(CACHE_TTL_SECONDS)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"BoldTrader serving on http://{args.host}:{args.port}/?q=HP+Z440&loc=Dallas%2C+TX&m={args.market}")
    server.serve_forever()


if __name__ == "__main__":
    main()
