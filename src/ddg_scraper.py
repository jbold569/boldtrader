"""DuckDuckGo HTML scraper: interim mock until eBay API access lands.

Uses the server-rendered html.duckduckgo.com endpoint (no JS required).
Known limit: anonymous use from datacenter IPs gets rate-challenged (HTTP 202);
residential IPs work. Swap for EbayBrowseApi when the keyset arrives.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .marketplace import Listing, Marketplace, SearchResult

PAGE_SIZE = 10  # DDG html endpoint page size
_BASE = "https://html.duckduckgo.com/html/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
        "Gecko/20100101 Firefox/131.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _real_url(href: str) -> str:
    """DDG wraps result URLs in a /l/?uddg=<encoded> redirect; unwrap it."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    q = parse_qs(urlparse(href).query)
    if "uddg" in q:
        return q["uddg"][0]
    return href


class DdgScraper(Marketplace):
    """Scrapes DuckDuckGo's server-rendered HTML search."""

    name = "duckduckgo"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        page = max(1, page)
        params = {
            "q": query,
            "s": (page - 1) * PAGE_SIZE,
            "dc": (page - 1) * PAGE_SIZE + 1,
        }
        resp = self._session.get(_BASE, params=params, timeout=15)
        if resp.status_code == 202:
            # DDG rate challenge: anonymous quota exhausted for this IP
            raise RuntimeError("DuckDuckGo rate limit reached (HTTP 202)")
        resp.raise_for_status()
        return self._parse(resp.text, page)

    def _parse(self, html: str, page: int) -> SearchResult:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[Listing] = []
        for r in soup.select(".result.web-result"):
            a = r.select_one(".result__a")
            if a is None:
                continue
            snippet_el = r.select_one(".result__snippet")
            listings.append(
                Listing(
                    id=_real_url(a.get("href", "")),
                    title=a.get_text(" ", strip=True),
                    price=None,
                    condition=None,
                    sold_count=None,
                    image_url=None,
                    url=_real_url(a.get("href", "")),
                    snippet=snippet_el.get_text(" ", strip=True) if snippet_el else None,
                )
            )

        n = len(listings)
        # DDG exposes no total count; assume more pages if this page was full.
        if n == PAGE_SIZE:
            total = page * PAGE_SIZE + 1
        else:
            total = (page - 1) * PAGE_SIZE + n

        return SearchResult(
            listings=listings,
            total_results=total,
            page=page,
            page_size=PAGE_SIZE,
        )
