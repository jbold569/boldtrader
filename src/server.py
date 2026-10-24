"""BoldTrader: marketplace search + Bargain Search chat authoring.

Run:  .venv/bin/python -m src.server [--port 8000]
Search: /?q=dell+desktop&loc=Kenmore&m=all   (m: all|offerup|facebook)
Bargain Search chat: /chat  (refine an existing search: /chat?id=N)
"""

from __future__ import annotations

import argparse
import logging
import html
import json
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import chat as chat_mod
from . import enhanced
from .db import get_connection, init_db
from .ebay_scraper import EbayScraper
from .facebook_scraper import FacebookScraper
from .fanout import enrichment_worker, fan_out
from .marketplace import Listing, Marketplace, SearchResult
from .offerup_scraper import OfferupScraper


CACHE_TTL_SECONDS = 15 * 60
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
CHAT_TEMPLATE_PATH = Path(__file__).parent / "templates" / "chat.html"
_template = string.Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
_chat_template = string.Template(CHAT_TEMPLATE_PATH.read_text(encoding="utf-8"))


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


def render_chat_page(
    transcript: list[dict],
    draft: dict | None = None,
    search: dict | None = None,
    banner: str = "",
) -> str:
    """Render the authoring/refinement chat page.

    `transcript` is the in-session message list; it travels through the page
    in a hidden JSON field so the stateless server can continue the thread.
    `draft`, when present, renders the confirmation form (contract signing).
    """
    msgs = []
    for m in transcript:
        cls = "user" if m["role"] == "user" else "assistant"
        who = "You" if m["role"] == "user" else "BoldTrader"
        msgs.append(
            f'<div class="msg {cls}"><strong>{who}</strong>'
            f"{html.escape(m['content'])}</div>"
        )
    if draft is not None:
        tp = draft.get("target_price")
        confirm = (
            '<form class="confirm" method="post" action="/confirm">'
            '<p class="note">Confirm this Bargain Search — edit anything inline first.</p>'
            '<label>Summary<input type="text" name="summary" '
            f'value="{html.escape(draft["summary"])}"></label>'
            '<label>Product identity<input type="text" name="product_identity" '
            f'value="{html.escape(draft["product_identity"])}"></label>'
            '<label>Queries (one per line)<textarea name="queries" rows="5">'
            f"{html.escape(chr(10).join(draft['queries']))}</textarea></label>"
            '<label>Exclusions (one per line)<textarea name="exclusions" rows="3">'
            f"{html.escape(chr(10).join(draft['exclusions']))}</textarea></label>"
            '<label>Target price (optional, e.g. 150)<input type="text" name="target_price" '
            f'value="{html.escape("" if tp is None else str(tp))}"></label>'
            '<label>Location<input type="text" name="location" '
            f'value="{html.escape(draft.get("location") or "Kenmore, WA")}" '
            'placeholder="City, State"></label>'
            f'<input type="hidden" name="transcript" value="{html.escape(json.dumps(transcript))}">'
            f'<input type="hidden" name="search_id" value="{(search or {}).get("id", "")}">'
            "<button type=\"submit\">Confirm Bargain Search</button>"
            "</form>"
        )
    else:
        confirm = ""
    heading = f"Refine: {search['summary']}" if search else "New bargain search"
    return _chat_template.substitute(
        heading=html.escape(heading),
        banner=f'<div class="banner">{html.escape(banner)}</div>' if banner else "",
        transcript="\n".join(msgs)
        if msgs
        else '<p class="empty">Tell me what you want to buy.</p>',
        confirm=confirm,
        transcript_json=html.escape(json.dumps(transcript)),
        search_id=(search or {}).get("id", ""),
    )


class Handler(BaseHTTPRequestHandler):
    marketplaces: dict[str, Marketplace]
    fanout_marketplaces: dict[str, Marketplace]
    default_market: str
    cache: _Cache

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path == "/chat":
            self._handle_chat_get(parsed)
            return
        if parsed.path == "/search":
            self._handle_enhanced_get(parsed)
            return
        if parsed.path in ("/", "/index.html", "/searches"):
            self._handle_searches_get()
            return
        if parsed.path != "/raw":
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

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path == "/chat":
            self._handle_chat_post()
        elif parsed.path == "/confirm":
            self._handle_confirm_post()
        elif parsed.path == "/reject":
            self._handle_reject_post()
        elif parsed.path == "/describe":
            self._handle_describe_post()
        else:
            self._send(404, "Not found")

    def _read_form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(body)

    def _handle_chat_get(self, parsed) -> None:
        """Open the chat: empty for a new search, DB transcript to refine one."""
        search_id = (parse_qs(parsed.query).get("id") or [""])[0]
        if not search_id:
            self._send(200, render_chat_page([]))
            return
        conn = get_connection()
        try:
            search = chat_mod.get_search(conn, int(search_id))
            if search is None:
                self._send(404, f"No bargain search with id {search_id}")
                return
            transcript = chat_mod.load_transcript(conn, search["id"])
        finally:
            conn.close()
        self._send(200, render_chat_page(transcript, search=search))

    def _handle_chat_post(self) -> None:
        """One authoring turn: LLM reply, draft if ready; persist when refining."""
        form = self._read_form()
        message = (form.get("message") or [""])[0].strip()
        if not message:
            self._send(200, render_chat_page([], banner="Type a message first."))
            return
        try:
            transcript = json.loads((form.get("transcript") or ["[]"])[0])
        except ValueError:
            transcript = []
        search_id = (form.get("search_id") or [""])[0]
        search = None
        conn = get_connection()
        try:
            if search_id:
                search = chat_mod.get_search(conn, int(search_id))
            try:
                reply, draft = chat_mod.next_reply(transcript, message, search)
            except Exception as exc:
                self._send(
                    200,
                    render_chat_page(
                        transcript,
                        search=search,
                        banner=f"Model call failed ({exc.__class__.__name__}); try again.",
                    ),
                )
                return
            transcript = transcript + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ]
            if search is not None:
                chat_mod.append_message(conn, search["id"], "user", message)
                chat_mod.append_message(conn, search["id"], "assistant", reply)
        finally:
            conn.close()
        self._send(200, render_chat_page(transcript, draft=draft, search=search))

    def _handle_confirm_post(self) -> None:
        """Contract signing: create or refine the Bargain Search from the form."""
        form = self._read_form()
        search_id = (form.get("search_id") or [""])[0]
        try:
            transcript = json.loads((form.get("transcript") or ["[]"])[0])
        except ValueError:
            transcript = []
        try:
            draft = chat_mod.draft_from_form(form)
        except chat_mod.DraftError as exc:
            # Re-render the form with whatever was submitted, flagged.
            echoed = {
                "summary": (form.get("summary") or [""])[0],
                "product_identity": (form.get("product_identity") or [""])[0],
                "queries": (form.get("queries") or [""])[0].splitlines(),
                "exclusions": (form.get("exclusions") or [""])[0].splitlines(),
                "target_price": None,
                "location": (form.get("location") or [""])[0],
            }
            self._send(200, render_chat_page(transcript, draft=echoed, banner=str(exc)))
            return
        conn = get_connection()
        try:
            if search_id:
                chat_mod.update_search(conn, int(search_id), draft)
                new_id = int(search_id)
            else:
                new_id = chat_mod.create_search(conn, draft)
                for m in transcript:
                    chat_mod.append_message(conn, new_id, m["role"], m["content"])
            search = chat_mod.get_search(conn, new_id)
            saved_transcript = chat_mod.load_transcript(conn, new_id)
        finally:
            conn.close()
        self._send(
            200,
            render_chat_page(
                saved_transcript,
                search=search,
                banner=f"Bargain Search #{new_id} saved (v{search['version']}).",
            ),
        )
        threading.Thread(
            target=fan_out,
            args=(self.fanout_marketplaces, new_id, search["location"]),
            daemon=True,
        ).start()

    def _handle_enhanced_get(self, parsed) -> None:
        """Enhanced view: match-filtered cards with enrichment annotations."""
        qs = parse_qs(parsed.query)
        sid = (qs.get("id") or [""])[0]
        if not sid:
            self._send(404, "Missing search id")
            return
        show_all = (qs.get("all") or [""])[0] == "1"
        price_filter = (qs.get("price") or [""])[0] == "1"
        conn = get_connection()
        try:
            state = enhanced.view_cards(conn, int(sid), show_all=show_all, price_filter=price_filter)
        finally:
            conn.close()
        if state is None:
            self._send(404, f"No bargain search with id {sid}")
            return
        self._send(200, enhanced.render_enhanced_page(state, show_all=show_all, price_filter=price_filter))

    def _handle_searches_get(self) -> None:
        """Bargain Search list page."""
        conn = get_connection()
        try:
            searches = enhanced.list_searches(conn)
        finally:
            conn.close()
        self._send(200, enhanced.render_searches_page(searches))

    def _handle_reject_post(self) -> None:
        """Reject a card: record it and feed the exclusion list."""
        form = self._read_form()
        sid = (form.get("search_id") or [""])[0]
        lid = (form.get("listing_id") or [""])[0]
        reason = (form.get("reason") or [""])[0]
        if not sid or not lid:
            self._send(400, "Missing search_id or listing_id")
            return
        conn = get_connection()
        try:
            enhanced.reject_listing(conn, int(sid), lid, reason)
            state = enhanced.view_cards(
                conn, int(sid),
                show_all=(form.get("all") or [""])[0] == "1",
                price_filter=(form.get("price") or [""])[0] == "1",
            )
        finally:
            conn.close()
        if state is None:
            self._send(404, f"No bargain search with id {sid}")
            return
        self._send(
            200,
            enhanced.render_enhanced_page(
                state,
                show_all=(form.get("all") or [""])[0] == "1",
                price_filter=(form.get("price") or [""])[0] == "1",
                banner=f"Rejected: {reason}",
            ),
        )

    def _handle_describe_post(self) -> None:
        """Save an authored description on a listing card."""
        form = self._read_form()
        sid = (form.get("search_id") or [""])[0]
        lid = (form.get("listing_id") or [""])[0]
        text = (form.get("description") or [""])[0]
        if not sid or not lid:
            self._send(400, "Missing search_id or listing_id")
            return
        conn = get_connection()
        try:
            enhanced.set_authored_description(conn, lid, text)
            state = enhanced.view_cards(
                conn, int(sid),
                show_all=(form.get("all") or [""])[0] == "1",
                price_filter=(form.get("price") or [""])[0] == "1",
            )
        finally:
            conn.close()
        if state is None:
            self._send(404, f"No bargain search with id {sid}")
            return
        self._send(
            200,
            enhanced.render_enhanced_page(
                state,
                show_all=(form.get("all") or [""])[0] == "1",
                price_filter=(form.get("price") or [""])[0] == "1",
                banner="Authored description saved.",
            ),
        )

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
    print(f"BoldTrader serving on http://{args.host}:{args.port}/?q=HP+Z440&loc=Kenmore%2C+WA&m={args.market}")
    server.serve_forever()


if __name__ == "__main__":
    main()
