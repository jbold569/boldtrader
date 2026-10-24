"""Enhanced view (ticket 06) + Bargain Search list page.

The enhanced view is the product: match-filtered cards with Enrichment
annotations (✨ product / condition / bundle / confidence), pending and
failed markers, a show-all toggle that reveals not-matches as the safety
net, and an optional target-price filter (off by default). Rejecting a
card writes a `rejects` row and feeds the Bargain Search's exclusion list
so the next triage pass respects it. The user's authored description
always overrides AI enrichment.
"""

from __future__ import annotations

import html
import json
import sqlite3
import string
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "templates" / "enhanced.html"
LIST_TEMPLATE_PATH = Path(__file__).parent / "templates" / "searches.html"
_template = string.Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
_list_template = string.Template(LIST_TEMPLATE_PATH.read_text(encoding="utf-8"))

_ALL_FIELDS = ("manufacturer", "model", "config", "condition", "bundle")


def view_cards(
    conn: sqlite3.Connection,
    search_id: int,
    show_all: bool = False,
    price_filter: bool = False,
) -> dict | None:
    """Assemble the enhanced-view state for one Bargain Search.

    Default set is the match set (match + unsure); show_all adds the
    not-matches. Rejected listings never appear. The price filter drops
    listings whose asking price exceeds the target (or is missing).
    Returns None if the search doesn't exist.
    """
    row = conn.execute(
        "SELECT summary, target_price, listing_ids, status "
        "FROM bargain_searches WHERE id=?",
        (search_id,),
    ).fetchone()
    if row is None:
        return None
    summary, target_price, listing_ids_json, status = row
    verdicts: dict[str, str] = json.loads(listing_ids_json)
    if not show_all:
        verdicts = {k: v for k, v in verdicts.items() if v in ("match", "unsure")}
    search = {
        "id": search_id,
        "summary": summary,
        "target_price": target_price,
        "status": status,
    }
    if not verdicts:
        return {"search": search, "cards": []}
    placeholders = ",".join("?" * len(verdicts))
    cards = []
    for lid, raw, authored, estatus, product, condition, bundle, confidence in conn.execute(
        f"SELECT l.id, l.raw, l.authored_description, e.status, e.product, "
        f"e.condition, e.bundle, e.confidence "
        f"FROM listings l LEFT JOIN enrichments e ON e.listing_id = l.id "
        f"WHERE l.id IN ({placeholders}) AND l.id NOT IN "
        f"(SELECT listing_id FROM rejects WHERE bargain_search_id=?)",
        (*verdicts.keys(), search_id),
    ):
        data = json.loads(raw)
        price = data.get("price")
        if price_filter and target_price is not None:
            if price is None or price > target_price:
                continue
        cards.append(
            {
                "id": lid,
                "title": data.get("title") or "",
                "url": data.get("url") or "",
                "price": price,
                "marketplace": data.get("marketplace") or "",
                "verdict": verdicts.get(lid, "match"),
                "enrich_status": estatus or "pending",
                "product": json.loads(product) if product else None,
                "condition": condition,
                "bundle": json.loads(bundle) if bundle else None,
                "confidence": json.loads(confidence) if confidence else None,
                "authored": authored,
            }
        )
    return {"search": search, "cards": cards}


def reject_listing(
    conn: sqlite3.Connection, search_id: int, listing_id: str, reason: str
) -> None:
    """Reject a card: record it and feed the exclusion list for the next triage."""
    conn.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, ?, ?)",
        (search_id, listing_id, reason),
    )
    exclusions = json.loads(
        conn.execute(
            "SELECT exclusions FROM bargain_searches WHERE id=?", (search_id,)
        ).fetchone()[0]
    )
    if reason not in exclusions:
        exclusions.append(reason)
        conn.execute(
            "UPDATE bargain_searches SET exclusions=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (json.dumps(exclusions), search_id),
        )
    conn.commit()


def set_authored_description(
    conn: sqlite3.Connection, listing_id: str, text: str
) -> None:
    """Store the user's authored description (empty clears it)."""
    text = (text or "").strip()
    conn.execute(
        "UPDATE listings SET authored_description=? WHERE id=?",
        (text or None, listing_id),
    )
    conn.commit()


def _fmt_price(price) -> str:
    return f"${price:,.2f}" if price is not None else "?"


def _reject_reason(card: dict) -> str:
    product = card.get("product") or {}
    model = product.get("model")
    if model and model != "unknown":
        return f"not this: {model}"
    return f"not this: {card['title']}"


def _render_enrichment(card: dict) -> str:
    product = card.get("product") or {}
    conf = card.get("confidence") or {}

    def val(v) -> str:
        return "?" if not v or v == "unknown" else html.escape(str(v))

    def conf_of(field: str) -> str:
        return html.escape(str(conf.get(field) or "unknown"))

    fields = [
        f"manufacturer: {val(product.get('manufacturer'))} ({conf_of('manufacturer')})",
        f"model: {val(product.get('model'))} ({conf_of('model')})",
        f"config: {val(product.get('config'))} ({conf_of('config')})",
        f"condition: {val(card.get('condition'))} ({conf_of('condition')})",
    ]
    bundle = card.get("bundle") or []
    bundle_text = ", ".join(html.escape(x) for x in bundle) if bundle else "?"
    fields.append(f"bundle: {bundle_text} ({conf_of('bundle')})")
    low = any(conf.get(f) in ("low", "unknown") for f in _ALL_FIELDS)
    note = (
        '<div class="lowconf">Low confidence — an authored description overrides this.</div>'
        if low
        else ""
    )
    return f'<div class="enriched">✨ {" · ".join(fields)}{note}</div>'


def _render_card(card: dict, search_id: int) -> str:
    parts: list[str] = []
    badge = (
        f'<span class="badge badge-{card["marketplace"]}">{card["marketplace"]}</span>'
        if card["marketplace"]
        else ""
    )
    parts.append(
        f'<div class="titlerow">{badge}'
        f'<a class="title" href="{html.escape(card["url"])}" target="_blank" '
        f'rel="noopener">{html.escape(card["title"])}</a></div>'
    )
    parts.append(f'<div class="price">{_fmt_price(card["price"])}</div>')
    if card["verdict"] == "not_match":
        parts.append('<div class="notmatch">not a match</div>')
    elif card["verdict"] == "unsure":
        parts.append('<div class="review">needs review</div>')
    if card["authored"]:
        parts.append(f'<div class="authored">✍ {html.escape(card["authored"])}</div>')
    elif card["enrich_status"] == "enriched":
        parts.append(_render_enrichment(card))
    elif card["enrich_status"] == "failed":
        parts.append('<div class="failed">enrichment failed</div>')
    else:
        parts.append('<div class="pending">⏳ pending</div>')
    if card["enrich_status"] == "enriched":
        parts.append(
            '<form class="reject" method="post" action="/reject">'
            f'<input type="hidden" name="search_id" value="{search_id}">'
            f'<input type="hidden" name="listing_id" value="{html.escape(card["id"])}">'
            f'<input type="hidden" name="reason" value="{html.escape(_reject_reason(card))}">'
            '<button type="submit">Reject</button>'
            "</form>"
        )
    parts.append(
        '<form class="describe" method="post" action="/describe">'
        f'<input type="hidden" name="search_id" value="{search_id}">'
        f'<input type="hidden" name="listing_id" value="{html.escape(card["id"])}">'
        '<textarea name="description" rows="2" '
        'placeholder="Authored description — overrides AI enrichment">'
        f'{html.escape(card["authored"] or "")}</textarea>'
        "<button type=\"submit\">Save description</button>"
        "</form>"
    )
    return f'<li class="card">{"".join(parts)}</li>'


def _view_link(search_id: int, show_all: bool, price_filter: bool) -> str:
    link = f"/search?id={search_id}"
    if show_all:
        link += "&all=1"
    if price_filter:
        link += "&price=1"
    return link


def render_enhanced_page(
    state: dict,
    show_all: bool = False,
    price_filter: bool = False,
    banner: str = "",
) -> str:
    search = state["search"]
    cards = state["cards"]
    toggles = [
        (
            f'<a href="/search?id={search["id"]}">show matches only</a>'
            if show_all
            else f'<a href="/search?id={search["id"]}&all=1">show all</a>'
        )
    ]
    if search["target_price"] is not None:
        if price_filter:
            toggles.append(
                f'<a href="/search?id={search["id"]}'
                f'{"&all=1" if show_all else ""}">price filter off</a>'
            )
        else:
            toggles.append(
                f'<a href="/search?id={search["id"]}'
                f'{"&all=1" if show_all else ""}&price=1">'
                f"filter ≤ ${search['target_price']:,.0f}</a>"
            )
    return _template.substitute(
        search_id=search["id"],
        summary=html.escape(search["summary"]),
        status=html.escape(search["status"]),
        count=len(cards),
        toggles=" · ".join(toggles),
        banner=f'<div class="banner">{html.escape(banner)}</div>' if banner else "",
        rows="\n".join(_render_card(c, search["id"]) for c in cards)
        or '<li class="card">No listings in this view.</li>',
    )


def list_searches(conn: sqlite3.Connection) -> list[dict]:
    """One row per Bargain Search for the list page."""
    out = []
    for sid, summary, status, listing_ids_json, updated_at in conn.execute(
        "SELECT id, summary, status, listing_ids, updated_at "
        "FROM bargain_searches ORDER BY id"
    ):
        verdicts = json.loads(listing_ids_json)
        ids = [lid for lid, v in verdicts.items() if v in ("match", "unsure")]
        total = len(ids)
        pending = 0
        if total:
            placeholders = ",".join("?" * total)
            pending = conn.execute(
                f"SELECT COUNT(*) FROM enrichments "
                f"WHERE status='pending' AND listing_id IN ({placeholders})",
                ids,
            ).fetchone()[0]
        if status in ("running", "enriching"):
            shown = f"running {total - pending}/{total}"
        else:
            shown = status
        out.append(
            {
                "id": sid,
                "summary": summary,
                "status_shown": shown,
                "match_count": total,
                "updated_at": updated_at,
            }
        )
    return out


def render_searches_page(searches: list[dict], banner: str = "") -> str:
    rows = []
    for s in searches:
        rows.append(
            '<li class="row">'
            f'<a class="summary" href="/search?id={s["id"]}">{html.escape(s["summary"])}</a>'
            f'<span class="status">{html.escape(s["status_shown"])}</span>'
            f'<span class="count">{s["match_count"]} matches</span>'
            f'<span class="updated">{html.escape(s["updated_at"])}</span>'
            f'<form class="del" method="post" action="/delete" '
            f'onsubmit="return confirm(\'Delete this bargain search?\');">'
            f'<input type="hidden" name="search_id" value="{s["id"]}">'
            '<button type="submit">Delete</button>'
            "</form>"
            "</li>"
        )
    return _list_template.substitute(
        banner=f'<div class="banner">{html.escape(banner)}</div>' if banner else "",
        rows="\n".join(rows) or '<li class="row">No bargain searches yet.</li>',
    )
