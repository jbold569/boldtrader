"""Facebook Marketplace scraper: Playwright with a persistent login profile.

One-time setup (only if logged-out search stops working):
    .venv/bin/python -m src.facebook_scraper login
    (headed browser; log in by hand; the profile in .fb-profile/ persists.)

Verified live 2026-10-23: logged-out search from this IP returns real listings.
Card text order is price | title | location.

shortcut: FB rotates DOM classes on every deploy. If parsing returns 0 results
after working previously, dump the page HTML and fix _parse against it.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from .marketplace import Listing, ListingDetail, Marketplace, SearchResult

PROFILE_DIR = Path(__file__).resolve().parent.parent / ".fb-profile"
LOGIN_URL = "https://www.facebook.com/login/"
PAGE_SIZE = 24  # FB renders ~24 cards per viewport batch

# FB marketplace URLs use slugs, not city names.
_CITY_SLUGS = {
    "new york": "nyc", "los angeles": "la", "las vegas": "vegas",
    "chicago": "chicago", "houston": "houston", "san antonio": "sanantonio",
    "miami": "miami", "orlando": "orlando", "san diego": "sandiego",
    "baltimore": "baltimore", "cincinnati": "cincinnati", "denver": "denver",
    "fort worth": "fortworth", "jacksonville": "jacksonville",
    "memphis": "memphis", "nashville": "nashville", "philadelphia": "philly",
    "portland": "portland", "san jose": "sanjose", "tucson": "tucson",
    "atlanta": "atlanta", "boston": "boston", "columbus": "columbus",
    "detroit": "detroit", "honolulu": "honolulu", "kansas city": "kansascity",
    "new orleans": "neworleans", "phoenix": "phoenix", "seattle": "seattle",
    "milwaukee": "milwaukee", "sacramento": "sac", "austin": "austin",
    "charlotte": "charlotte", "dallas": "dallas", "el paso": "elpaso",
    "indianapolis": "indianapolis", "louisville": "louisville",
    "minneapolis": "minneapolis", "oklahoma city": "oklahoma",
    "pittsburgh": "pittsburgh", "san francisco": "sanfrancisco",
    "tampa": "tampa", "washington dc": "dc", "washington": "dc",
}


def _city_slug(location: str | None) -> str:
    if not location:
        return "kenmore"
    loc = location.strip().lower()
    if loc in _CITY_SLUGS:
        return _CITY_SLUGS[loc]
    # "Dallas, TX" -> "dallas"
    first = loc.split(",")[0].strip()
    return _CITY_SLUGS.get(first, first)


class FacebookScraper(Marketplace):
    """Playwright-driven FB Marketplace search using a persistent profile."""

    name = "facebook"

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless

    def login(self) -> None:
        """One-time interactive login. Headed browser; complete login + 2FA yourself."""
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LOGIN_URL)
            print("Log in in the browser window (including any 2FA/checkpoint)...")
            for _ in range(600):  # 10 min budget
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                if cookies.get("c_user"):
                    print("Logged in. Profile saved to", PROFILE_DIR)
                    ctx.close()
                    return
                time.sleep(1)
            ctx.close()
            raise RuntimeError("login not completed within 10 minutes")

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        city = _city_slug(location)
        url = f"https://www.facebook.com/marketplace/{city}/search/?query={query}"
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=self._headless)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded")
            try:
                pg.wait_for_selector('a[href*="/marketplace/item/"]', timeout=15000)
            except PWTimeout:
                ctx.close()
                raise RuntimeError(
                    "no listings rendered — session expired or layout changed; "
                    "re-run: .venv/bin/python -m src.facebook_scraper login"
                )
            html = pg.content()
            ctx.close()
        return self._parse(html, page)

    def fetch_detail(self, listing: Listing) -> ListingDetail:
        # Best-effort: meta tags carry the description and first photo and are
        # far more stable than FB's rotating DOM classes.
        url = listing.url.split("&ref")[0]
        if not url.startswith("http"):
            url = "https://www.facebook.com" + url
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=self._headless)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=30000)
                pg.wait_for_selector("meta[property='og:description']", state="attached", timeout=15000)
                html = pg.content()
            finally:
                ctx.close()
        soup = BeautifulSoup(html, "html.parser")

        desc = ""
        md = soup.find("meta", attrs={"property": "og:description"})
        if md and md.get("content"):
            desc = md["content"]

        images: list[str] = []
        og_img = soup.find("meta", attrs={"property": "og:image"})
        if og_img and og_img.get("content"):
            images.append(og_img["content"])

        # FB marketplace exposes no shipping/fees.
        return ListingDetail(description=desc, images=images, shipping_cost=None)

    def _parse(self, html: str, page: int) -> SearchResult:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[Listing] = []
        seen: set[str] = set()
        for a in soup.select('a[href*="/marketplace/item/"]'):
            href = a["href"].split("&ref")[0]
            item_id = re.sub(r"\D", "", href.split("?")[0].rsplit("/", 1)[-1]) or href
            if item_id in seen:
                continue
            seen.add(item_id)
            lines = [l for l in a.get_text("\n", strip=True).split("\n") if l]
            # FB card text order: [sale price] [original price] title location
            # (verified live 2026-10-23; sale cards carry two price lines)
            _PRICE = re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
            price = None
            title = ""
            for line in lines:
                if _PRICE.match(line):
                    if price is None:
                        price = float(line.replace(",", "").lstrip("$"))
                    continue
                title = line
                break
            img = a.find("img")
            listings.append(
                Listing(
                    id=item_id,
                    title=title,
                    price=price,
                    condition=None,
                    sold_count=None,
                    image_url=img.get("src") if img else None,
                    url=href,
                    snippet=None,
                )
            )
        n = len(listings)
        total = page * PAGE_SIZE + 1 if n >= PAGE_SIZE else (page - 1) * PAGE_SIZE + n
        return SearchResult(listings=listings, total_results=total, page=page, page_size=PAGE_SIZE)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "login":
        FacebookScraper().login()
    else:
        print("usage: python -m src.facebook_scraper login")
