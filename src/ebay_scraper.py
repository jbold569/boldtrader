"""eBay scraper: primitive search-page scraping until official API access lands.

See docs/adr/0005-interim-ebay-scraper-until-api-access.md. This class exists
behind the Marketplace interface so it can be swapped for an EbayBrowseApi
implementation without touching the server.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .marketplace import Listing, Marketplace, SearchResult

PAGE_SIZE = 50  # eBay's _ipg param

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
        "Gecko/20100101 Firefox/131.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_PRICE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{1,2})?)")
_COUNT_RE = re.compile(r"([\d,]+)\s*\+?\s*results")


def _parse_price(text: str) -> float | None:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    m = re.search(r"([\d,]+)", text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


class EbayScraper(Marketplace):
    """Scrapes eBay's public search results pages."""

    name = "ebay"
    base_url = "https://www.ebay.com/sch/i.html"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        params = {
            "_nkw": query,
            "_ipg": PAGE_SIZE,
            "_pgn": max(1, page),
        }
        resp = self._session.get(self.base_url, params=params, timeout=15)
        resp.raise_for_status()
        return self._parse(resp.text, page)

    def _parse(self, html: str, page: int) -> SearchResult:
        soup = BeautifulSoup(html, "html.parser")

        total = 0
        count_el = soup.select_one(".srp-controls__count-heading, .srp-controls__count")
        if count_el:
            parsed = _parse_count(count_el.get_text(" ", strip=True))
            total = parsed if parsed is not None else 0

        listings: list[Listing] = []
        for card in soup.select("li.s-card"):
            listing = self._parse_card(card)
            if listing is not None:
                listings.append(listing)

        if total == 0:
            total = len(listings)

        return SearchResult(
            listings=listings,
            total_results=total,
            page=page,
            page_size=PAGE_SIZE,
        )

    def _parse_card(self, card) -> Listing | None:
        title_el = card.select_one(".s-card__title")
        if title_el is None:
            return None
        link_el = card.find("a", href=True)
        url = link_el["href"] if link_el else ""
        if not url:
            return None

        price_el = card.select_one(".s-card__price")
        price = _parse_price(price_el.get_text(" ", strip=True)) if price_el else None

        condition_el = card.select_one(".s-card__subtitle")
        condition = condition_el.get_text(" ", strip=True) if condition_el else None

        sold_count = None
        for el in card.find_all(string=re.compile(r"\b[\d,]+\s+sold\b")):
            sold_count = _parse_int(el.strip())
            break

        image_url = None
        img = card.select_one(".s-card__media-wrapper img")
        if img:
            image_url = img.get("src") or img.get("data-src")

        return Listing(
            id=card.get("data-listingid") or url,
            title=title_el.get_text(" ", strip=True),
            price=price,
            condition=condition,
            sold_count=sold_count,
            image_url=image_url,
            url=url,
        )


def _parse_count(text: str) -> int | None:
    m = _COUNT_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None
