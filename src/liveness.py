"""Liveness: whether a Listing is still buyable on its marketplace right now.

Sold or deleted listings stay visible on the board, labelled "no longer
available". The check runs as a background sweep kicked off the first time
a board is opened (GET /api/v1/searches/{id}/liveness), so the page
itself never waits on the marketplaces.

Per-marketplace signals (verified live 2026-10-25):
  facebook  live    final URL is still the item URL and og:description present
            dead    redirected to /login, or no og:description
  offerup   dead    GraphQL detail errors with 404 / "no longer available"
  ebay      dead    HTTP 404/410, or "no longer available" text
Anything else (network error, anti-bot block) is 'unknown': never mark dead,
because a false "no longer available" on a live listing misleads the buyer.
"""

from __future__ import annotations

import json
import logging
import threading

from . import events
from .db import get_connection

log = logging.getLogger(__name__)

LIVE = "live"
DEAD = "dead"
UNKNOWN = "unknown"

# One sweep per search at a time. The dict is the single source of truth for
# "is a sweep running/finished, and with what banner".
_lock = threading.Lock()
_active: dict[int, dict] = {}

FB_HOME = "https://www.facebook.com/marketplace/"


def start(search_id: int) -> None:
    """Kick a liveness sweep for one Bargain Search. Never blocks the caller."""
    with _lock:
        cur = _active.get(search_id)
        if cur is not None and not cur.get("done"):
            return  # a sweep is already running for this search
        _active[search_id] = {"done": False, "banner": ""}
    threading.Thread(target=_sweep, args=(search_id,), daemon=True).start()


def kicked(search_id: int) -> bool:
    """Has a sweep ever been recorded for this search in this process?"""
    with _lock:
        return search_id in _active


def status(search_id: int) -> dict:
    """Current sweep state for the client poll."""
    with _lock:
        cur = _active.get(search_id)
        if cur is None:
            return {"done": True, "banner": "", "dead": []}
        return dict(cur)


def dead_error(exc: Exception) -> bool:
    """Does this fetch_detail exception look like a dead listing (not an outage)?"""
    text = str(exc).lower()
    return "404" in text or "410" in text or "no longer available" in text


def _update(conn, lid: str, availability: str) -> None:
    conn.execute(
        "UPDATE listings SET availability=?, availability_checked_at=CURRENT_TIMESTAMP "
        "WHERE id=?",
        (availability, lid),
    )
    conn.commit()


def _check_offerup(mp, data: dict) -> str:
    from .marketplace import Listing

    try:
        mp.fetch_detail(Listing(**data))
        return LIVE
    except Exception as exc:
        return DEAD if dead_error(exc) else UNKNOWN


def _check_ebay(mp, data: dict) -> str:
    import requests

    try:
        r = mp._session.get(data.get("url", ""), timeout=15)
    except requests.RequestException:
        return UNKNOWN
    if r.status_code in (404, 410):
        return DEAD
    if r.status_code >= 400:
        return UNKNOWN  # blocked/error: no evidence either way
    text = r.text.lower()
    if "item no longer available" in text or "this item has ended" in text:
        return DEAD
    return LIVE


_CHECKERS = {"offerup": _check_offerup, "ebay": _check_ebay}


def _fb_session_ok(ctx) -> bool:
    page = ctx.new_page()
    try:
        page.goto(FB_HOME, wait_until="domcontentloaded", timeout=30000)
        return "/login" not in page.url
    except Exception:
        return False
    finally:
        page.close()


def _fb_item_live(ctx, url: str) -> str:
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        og = False
        try:
            page.wait_for_selector(
                "meta[property='og:description']", state="attached", timeout=10000
            )
            og = True
        except Exception:
            pass
        if "/login" in page.url:
            return DEAD
        return LIVE if og else DEAD
    except Exception:
        return UNKNOWN
    finally:
        page.close()


def _fb_url(url: str) -> str:
    """Normalize an FB item URL the same way FacebookScraper.fetch_detail does."""
    url = (url or "").split("&ref")[0]
    if not url.startswith("http"):
        url = "https://www.facebook.com" + url
    return url


def _sweep_facebook(items: list[tuple[str, dict]], conn) -> tuple[int, str]:
    """Check all FB items in one browser session. Returns (dead_count, banner).

    Home-probe first: if the saved FB login is dead, every item redirects to
    /login and we would falsely mark the whole board dead. We also re-probe
    home once after the first dead mark: a session that dies mid-sweep aborts
    the rest instead of poisoning them.
    """
    from playwright.sync_api import sync_playwright

    from .facebook_scraper import PROFILE_DIR

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=True)
        if not _fb_session_ok(ctx):
            ctx.close()
            return 0, (
                "Facebook session expired — re-run: "
                ".venv/bin/python -m src.facebook_scraper login. "
                "Facebook listings were not re-checked."
            )
        dead = 0
        verified_first_dead = False
        for lid, data in items:
            url = _fb_url(data.get("url", ""))
            state = _fb_item_live(ctx, url)
            if state == DEAD and not verified_first_dead:
                # Distinguish "this item is deleted" from "the session just died".
                if not _fb_session_ok(ctx):
                    ctx.close()
                    return dead, (
                        "Facebook session expired mid-check — re-run: "
                        ".venv/bin/python -m src.facebook_scraper login. "
                        "Remaining Facebook listings were not re-checked."
                    )
                verified_first_dead = True
            if state != UNKNOWN:
                _update(conn, lid, state)
                if state == DEAD:
                    dead += 1
        ctx.close()
        return dead, ""


def _sweep(search_id: int) -> None:
    """Re-check every listing in one Bargain Search, updating rows as it goes."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
        ).fetchone()
        if row is None:
            _mark_done(search_id, "Bargain search not found.")
            return
        ids = list(json.loads(row[0]).keys())
        if not ids:
            _mark_done(search_id, "")
            return
        by_mp: dict[str, list[tuple[str, dict]]] = {}
        for lid, raw in conn.execute(
            f"SELECT id, raw FROM listings WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        ):
            data = json.loads(raw)
            mp_name = data.get("marketplace") or lid.split(":", 1)[0]
            by_mp.setdefault(mp_name, []).append((lid, data))
        banner = ""
        for mp_name, items in by_mp.items():
            if mp_name == "facebook":
                d, banner = _sweep_facebook(items, conn)
                log.info("liveness sweep #%s: facebook %s dead", search_id, d)
                continue
            checker = _CHECKERS.get(mp_name)
            if checker is None:
                continue
            mp = _marketplace_for(mp_name)
            for lid, data in items:
                state = checker(mp, data)
                if state != UNKNOWN:
                    _update(conn, lid, state)
        _mark_done(search_id, banner)
    except Exception as exc:
        log.exception("liveness sweep #%s crashed", search_id)
        _mark_done(search_id, f"Liveness check failed: {exc}")
    finally:
        conn.close()


def _mark_done(search_id: int, banner: str) -> None:
    dead = _dead_ids(search_id)
    with _lock:
        _active[search_id] = {"done": True, "banner": banner, "dead": dead}
    events.publish(
        "liveness",
        {"search_id": search_id, "done": True, "dead_count": len(dead), "banner": banner},
    )


def _dead_ids(search_id: int) -> list[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT listing_ids FROM bargain_searches WHERE id=?", (search_id,)
        ).fetchone()
        if row is None:
            return []
        ids = list(json.loads(row[0]).keys())
        if not ids:
            return []
        rows = conn.execute(
            f"SELECT id FROM listings WHERE availability='{DEAD}' "
            f"AND id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
        return [r[0] for r in rows]
    except (TypeError, json.JSONDecodeError):
        return []
    finally:
        conn.close()


_MARKETPLACE_SINGLETONS: dict[str, object] = {}


def _marketplace_for(name: str):
    if name not in _MARKETPLACE_SINGLETONS:
        if name == "offerup":
            from .offerup_scraper import OfferupScraper

            _MARKETPLACE_SINGLETONS[name] = OfferupScraper()
        elif name == "ebay":
            from .ebay_scraper import EbayScraper

            _MARKETPLACE_SINGLETONS[name] = EbayScraper()
        else:
            _MARKETPLACE_SINGLETONS[name] = None
    return _MARKETPLACE_SINGLETONS[name]
