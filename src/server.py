"""BoldTrader: marketplace search + Bargain Search chat authoring.

Run:  .venv/bin/python -m src.server [--port 10000]   (dev ports live in the 10000 range)
Search: /search?q=dell+desktop&loc=Kenmore&m=all   (m: all|offerup|facebook)
Advanced: the "Advanced" form on /search creates a Bargain Search directly.
Enhanced view: /search?id=N
Chat: /chat  (no id resumes the latest session; /chat?id=N opens one)
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
from . import liveness
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

STATIC_DIR = Path(__file__).parent / "templates"
STATIC_TYPES = {".css": "text/css", ".js": "application/javascript"}


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
    return f"/search?q={quote(query)}&loc={quote(location)}&m={market}&page={page}"


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
        price = f'<div class="price">${l.price:,.2f}</div>' if l.price is not None else ""
        rows.append(
            f'<li class="card">'
            f'<div class="head">{img}'
            f'<div class="titlerow">{badge}'
            f'<a class="title" href="{l.url}" target="_blank" rel="noopener">{l.title}</a></div>'
            f"{price}</div>"
            f"{meta}{snippet}"
            f"</li>"
        )
    return "\n".join(rows) if rows else '<li class="card">No listings found.</li>'


def _render_advanced(values: dict, hidden: bool = True) -> str:
    """Bargain Search authoring form, hidden until the Advanced toggle is on."""
    esc = html.escape

    def v(key: str, default: str = "") -> str:
        val = values.get(key) or default
        return str(val)

    hidden_attr = " hidden" if hidden else ""
    sid = values.get("search_id")
    hidden_id = f'<input type="hidden" name="search_id" value="{esc(str(sid))}">' if sid else ""
    return (
        f'<div id="advanced"{hidden_attr}>'
        f'<form class="confirm" method="post" action="/search">{hidden_id}'
        f'<label>Summary<input type="text" name="summary" value="{esc(v("summary"))}"></label>'
        f'<label>Product identity<input type="text" name="product_identity" value="{esc(v("product_identity"))}"></label>'
        f'<label>Queries (one per line)<textarea name="queries" rows="5">{esc(v("queries"))}</textarea></label>'
        f'<label>Exclusions (one per line)<textarea name="exclusions" rows="3">{esc(v("exclusions"))}</textarea></label>'
        f'<label>Target price (optional, e.g. 150)<input type="text" name="target_price" value="{esc(v("target_price"))}"></label>'
        f'<label>Location<input type="text" name="location" value="{esc(v("location", "Kenmore, WA"))}" placeholder="City, State"></label>'
        '<button type="submit">Create Bargain Search</button>'
        "</form>"
        "</div>"
    )


_drawer = chat_mod.drawer_html


def render_page(
    query: str = "",
    result: SearchResult | None = None,
    location: str = "",
    banner: str = "",
    source: str = "offerup",
    advanced: dict | None = None,
    advanced_open: bool = False,
    drawer: str = "",
) -> str:
    if result is None:
        result = SearchResult()
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
        advanced=_render_advanced(advanced or {}, hidden=not advanced_open),
        drawer=drawer or _drawer(),
    )


def render_chat_page(
    transcript: list[dict],
    drafts: list[dict] | None = None,
    session: dict | None = None,
    banner: str = "",
    banner_cls: str = "banner",
    drawer: str = "",
) -> str:
    """Render the chat page for a Chat Session.

    `transcript` is the session's message list loaded from the DB; it also
    travels through the page in a hidden JSON field so chat.js can
    markdown-render assistant replies. `drafts`, when present, render one
    confirmation form per proposed Bargain Search (contract signing).
    """
    msgs = []
    pending_calls: list[dict] = []  # tool calls awaiting their rendered chip
    for m in transcript:
        if m["role"] == "tool":
            call = pending_calls.pop(0) if pending_calls else {}
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            query = next(iter(args.values()), "")
            chip = chat_mod.chip_text(fn.get("name", "tool"), query, m["content"])
            msgs.append(f'<div class="chip">&#128269; {html.escape(chip)}</div>')
            continue
        if m["role"] == "assistant":
            try:
                data = json.loads(m["content"])
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get("tool_calls"):
                # The chips stand in for this row; no raw JSON on the page.
                pending_calls.extend(data["tool_calls"])
                continue
        cls = "user" if m["role"] == "user" else "assistant"
        who = "You" if m["role"] == "user" else "BoldTrader"
        msgs.append(
            f'<div class="msg {cls}"><strong>{who}</strong>'
            f"{html.escape(m['content'])}</div>"
        )
    session_id = (session or {}).get("id", "")
    confirm = ""
    for draft in drafts or []:
        tp = draft.get("target_price")
        confirm += (
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
            f'<input type="hidden" name="session_id" value="{session_id}">'
            "<button type=\"submit\">Confirm Bargain Search</button>"
            "</form>"
        )
    heading = (session or {}).get("title") or "New chat"
    return _chat_template.substitute(
        heading=html.escape(heading),
        banner=f'<div class="{banner_cls}">{html.escape(banner)}</div>' if banner else "",
        transcript="\n".join(msgs)
        if msgs
        else '<p class="empty">Tell me what you want to buy.</p>',
        confirm=confirm,
        transcript_json=html.escape(json.dumps(transcript)),
        session_id=session_id,
        drawer=drawer or _drawer(),
    )


class Handler(BaseHTTPRequestHandler):
    marketplaces: dict[str, Marketplace]
    fanout_marketplaces: dict[str, Marketplace]
    default_market: str
    cache: _Cache

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if Path(parsed.path).suffix in STATIC_TYPES:
            self._serve_static(parsed.path)
            return
        if parsed.path == "/chat":
            self._handle_chat_get(parsed)
            return
        if parsed.path == "/search":
            qs = parse_qs(parsed.query)
            sid = (qs.get("id") or [""])[0]
            if sid:
                if (qs.get("modify") or [""])[0] == "1":
                    self._handle_modify_get(sid)
                else:
                    self._handle_enhanced_get(parsed)
            else:
                self._handle_raw_search(parsed)
            return
        if parsed.path == "/liveness":
            self._handle_liveness_get(parsed)
            return
        if parsed.path in ("/", "/index.html", "/searches"):
            self._handle_searches_get()
            return
        self._send(404, "Not found")

    def _handle_raw_search(self, parsed) -> None:
        """Raw keyword search: query/location/marketplace with pagination."""
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

    def _handle_modify_get(self, sid: str) -> None:
        """Pre-filled advanced form for modifying an existing Bargain Search;
        unknown id falls back to the normal (closed-form) search page."""
        conn = get_connection()
        try:
            search = chat_mod.get_search(conn, int(sid))
        finally:
            conn.close()
        if search is None:
            self._handle_raw_search(urlparse("/search"))
            return
        values = dict(search)
        values["search_id"] = search["id"]
        values["queries"] = "\n".join(search["queries"])
        values["exclusions"] = "\n".join(search["exclusions"])
        self._send(200, render_page(advanced=values, advanced_open=True))

    def _handle_search_post(self) -> None:
        """Advanced Bargain Search: create (or update with search_id), then
        open the search's enhanced view."""
        form = self._read_form()
        if not (form.get("summary") or [""])[0].strip():
            # An omitted summary stands in as the product identity, pre-validation.
            form = dict(form, summary=[(form.get("product_identity") or [""])[0]])
        try:
            draft = chat_mod.draft_from_form(form)
        except chat_mod.DraftError as exc:
            # Re-render the form with whatever was submitted, flagged.
            values = {
                k: (form.get(k) or [""])[0]
                for k in (
                    "summary",
                    "product_identity",
                    "queries",
                    "exclusions",
                    "target_price",
                    "location",
                )
            }
            editing = (form.get("search_id") or [""])[0]
            if editing:
                values["search_id"] = editing
            self._send(200, render_page(advanced=values, advanced_open=True, banner=str(exc)))
            return
        conn = get_connection()
        try:
            editing = (form.get("search_id") or [""])[0]
            if editing:
                chat_mod.update_search(conn, int(editing), draft)
                saved_id = int(editing)
            else:
                saved_id = chat_mod.create_search(conn, draft)
        finally:
            conn.close()
        self.send_response(303)
        self.send_header("Location", f"/search?id={saved_id}")
        self.send_header("Content-Length", "0")
        self.end_headers()
        # Fan-out starts after the redirect is on the wire, not before.
        threading.Thread(
            target=fan_out,
            args=(self.fanout_marketplaces, saved_id, draft["location"]),
            daemon=True,
        ).start()

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path == "/chat":
            self._handle_chat_post()
        elif parsed.path == "/search":
            self._handle_search_post()
        elif parsed.path == "/confirm":
            self._handle_confirm_post()
        elif parsed.path == "/reject":
            self._handle_reject_post()
        elif parsed.path == "/describe":
            self._handle_describe_post()
        elif parsed.path == "/delete":
            self._handle_delete_post()
        else:
            self._send(404, "Not found")

    def _read_form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(body)

    def _handle_chat_get(self, parsed) -> None:
        """Open the chat: no id resumes the latest session; ?id=N opens one;
        ?new=1 (the drawer's New Chat) always starts a fresh empty chat."""
        session_id = (parse_qs(parsed.query).get("id") or [""])[0]
        fresh = (parse_qs(parsed.query).get("new") or [""])[0] == "1"
        conn = get_connection()
        try:
            if fresh:
                self._send(200, render_chat_page([]))
                return
            if session_id:
                session = chat_mod.get_session(conn, int(session_id))
                if session is None:
                    self._send(404, f"No chat session with id {session_id}")
                    return
            else:
                session = chat_mod.latest_session(conn)
            if session is None:
                self._send(200, render_chat_page([]))
                return
            transcript = chat_mod.load_session_transcript(conn, session["id"])
        finally:
            conn.close()
        self._send(200, render_chat_page(transcript, session=session))

    def _handle_chat_post(self) -> None:
        """One chat turn. No session_id means start a new session."""
        form = self._read_form()
        message = (form.get("message") or [""])[0].strip()
        if not message:
            self._send(200, render_chat_page([], banner="Type a message first."))
            return
        session_id = (form.get("session_id") or [""])[0]
        conn = get_connection()
        try:
            if session_id:
                session = chat_mod.get_session(conn, int(session_id))
                if session is None:
                    self._send(404, f"No chat session with id {session_id}")
                    return
            else:
                sid = chat_mod.create_session(conn, chat_mod.generate_title(message))
                session = chat_mod.get_session(conn, sid)
            transcript = chat_mod.load_session_transcript(conn, session["id"])
            try:
                reply, drafts, turn_rows = chat_mod.next_reply(
                    transcript, message, conn=conn, session_id=session["id"]
                )
            except Exception as exc:
                # next_reply saved the user row before its first model call.
                rendered = chat_mod.load_session_transcript(conn, session["id"])
                self._send(
                    200,
                    render_chat_page(
                        rendered,
                        session=session,
                        banner=f"Model call failed ({exc.__class__.__name__}); try again.",
                    ),
                )
                return
            transcript = transcript + turn_rows
        finally:
            conn.close()
        self._send(200, render_chat_page(transcript, drafts=drafts, session=session))

    def _handle_confirm_post(self) -> None:
        """Contract signing: create the Bargain Search from the confirmed draft."""
        form = self._read_form()
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
            self._send(200, render_chat_page([], drafts=[echoed], banner=str(exc)))
            return
        conn = get_connection()
        try:
            new_id = chat_mod.create_search(conn, draft)
            search = chat_mod.get_search(conn, new_id)
            session_id = (form.get("session_id") or [""])[0]
            session = (
                chat_mod.get_session(conn, int(session_id)) if session_id else None
            )
            transcript = (
                chat_mod.load_session_transcript(conn, session["id"])
                if session
                else []
            )
        finally:
            conn.close()
        self._send(
            200,
            render_chat_page(
                transcript,
                session=session,
                banner=f"Bargain Search #{new_id} saved (v{search['version']}).",
                banner_cls="toast",
            ),
        )
        threading.Thread(
            target=fan_out,
            args=(self.fanout_marketplaces, new_id, search["location"]),
            daemon=True,
        ).start()

    def _handle_enhanced_get(self, parsed) -> None:
        """Enhanced view: match-filtered cards with enrichment annotations.

        Kicking the liveness sweep only after the response is sent keeps the
        page instant; the page polls /liveness to update "no longer
        available" labels as the sweep progresses.
        """
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
        banner = liveness.status(int(sid)).get("banner", "")
        self._send(
            200,
            enhanced.render_enhanced_page(
                state,
                show_all=show_all,
                price_filter=price_filter,
                banner=banner,
                drawer=_drawer(),
            ),
        )
        liveness.start(int(sid))

    def _handle_liveness_get(self, parsed) -> None:
        """JSON poll target for the enhanced view's liveness sweep."""
        qs = parse_qs(parsed.query)
        sid = (qs.get("id") or [""])[0]
        if not sid:
            self._send(400, "Missing search id")
            return
        self._send(200, json.dumps(liveness.status(int(sid))),
                  content_type="application/json")

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

    def _handle_delete_post(self) -> None:
        """Delete a Bargain Search and return to the list page."""
        form = self._read_form()
        sid = (form.get("search_id") or [""])[0]
        if not sid:
            self._send(400, "Missing search_id")
            return
        conn = get_connection()
        try:
            chat_mod.delete_search(conn, int(sid))
            searches = enhanced.list_searches(conn)
        finally:
            conn.close()
        self._send(
            200,
            enhanced.render_searches_page(searches, banner=f"Deleted bargain search #{sid}."),
        )

    def _send(self, status: int, body: str, content_type: str = "text/html") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        f = (STATIC_DIR / path.lstrip("/")).resolve()
        if not f.is_file() or STATIC_DIR.resolve() not in f.parents:
            self._send(404, "Not found")
            return
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(f.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
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
    print(f"BoldTrader serving on http://{args.host}:{args.port}/search?q=HP+Z440&loc=Kenmore%2C+WA&m={args.market}")
    server.serve_forever()


if __name__ == "__main__":
    main()
