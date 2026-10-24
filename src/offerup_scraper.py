"""OfferUp scraper: anonymous GetModularFeed GraphQL search.

OfferUp has no official API. This uses the site's internal GraphQL endpoint,
which works without login via a client-minted device token. ToS prohibits
automated collection (see docs/research/offerup-search.md §4); we accept the
contract-level risk for read-only, no-account search.

The 2021 everettperiman/OfferupUnofficalAPI repo this was modeled on uses a
legacy REST endpoint (webapi/search/v4/feed) that now returns 410 Gone. The
current route is GraphQL, verified live 2026-10-23.
"""

from __future__ import annotations

import secrets

import requests

from .marketplace import Listing, ListingDetail, Marketplace, SearchResult

PAGE_SIZE = 50
_GRAPHQL_URL = "https://offerup.com/api/graphql"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
    "Gecko/20100101 Firefox/131.0"
)

# Minimal query: listing tiles + next-page cursor. Verified against live schema.
_QUERY = """
query GetModularFeed($searchParams: [SearchParam], $debug: Boolean = false) {
  modularFeed(params: $searchParams, debug: $debug) {
    looseTiles {
      __typename
      ... on ModularFeedTileListing {
        listing {
          listingId
          title
          price
          conditionText
          locationName
          image { url }
        }
      }
    }
    pageCursor
  }
}
"""

# Detail query: full description, photos, shipping rate. Verified anonymous 2026-10-24.
_DETAIL_QUERY = """
query ListingDetail($listingId: ID!) {
  listing(listingId: $listingId) {
    description
    price
    shippingRate { price }
    photos { uuid detail { url } }
  }
}
"""


def _to_price(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


class OfferupScraper(Marketplace):
    """Anonymous OfferUp search via the internal GetModularFeed GraphQL feed."""

    name = "offerup"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        # Cursor chain: (query, page) -> pageCursor returned after that page.
        self._cursors: dict[tuple[str, int], str] = {}
        # Geocode cache: location string -> (lat, lon)
        self._geo: dict[str, tuple[str, str]] = {}

    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        page = max(1, page)
        lat, lon = self._geocode(location)

        if page == 1:
            listings, cursor = self._fetch(query, None, lat, lon)
            self._cursors[(query.lower(), 1)] = cursor
            return self._build(listings, 1, cursor)

        cursor = self._cursors.get((query.lower(), page - 1))
        if cursor is None:
            # Walk from page 1 to collect the cursor chain up to page-1.
            walk = None
            for p in range(1, page):
                _, walk = self._fetch(query, walk, lat, lon)
                self._cursors[(query.lower(), p)] = walk
                if walk is None:
                    break
            cursor = walk

        if cursor is None:
            return SearchResult(listings=[], total_results=0, page=page, page_size=PAGE_SIZE)

        listings, cursor = self._fetch(query, cursor, lat, lon)
        self._cursors[(query.lower(), page)] = cursor
        return self._build(listings, page, cursor)

    def fetch_detail(self, listing: Listing) -> ListingDetail:
        resp = self._session.post(
            _GRAPHQL_URL,
            json={
                "operationName": "ListingDetail",
                "query": _DETAIL_QUERY,
                "variables": {"listingId": listing.id},
            },
            headers={
                "Content-Type": "application/json",
                "User-Agent": _UA,
                "x-ou-operation-name": "ListingDetail",
                "x-ou-d-token": "web-" + secrets.token_hex(28),
                "x-ou-version": "2026.1.0",
            },
            timeout=15,
        )
        if resp.status_code in (403, 429):
            raise RuntimeError(f"OfferUp blocked the request (HTTP {resp.status_code})")
        resp.raise_for_status()

        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"OfferUp GraphQL error: {data['errors'][0]['message']}")

        rec = (data.get("data") or {}).get("listing")
        if not rec:
            raise RuntimeError(f"OfferUp returned no detail for {listing.id}")

        images = [
            (ph.get("detail") or {}).get("url")
            for ph in rec.get("photos") or []
            if (ph.get("detail") or {}).get("url")
        ]
        rate = rec.get("shippingRate") or {}
        return ListingDetail(
            description=rec.get("description") or "",
            images=images,
            shipping_cost=_to_price(rate.get("price")),
        )

    def _build(self, listings: list[Listing], page: int, cursor) -> SearchResult:
        n = len(listings)
        total = (page - 1) * PAGE_SIZE + n
        if n == PAGE_SIZE and cursor:
            total += 1  # assume at least one more page
        return SearchResult(
            listings=listings,
            total_results=total,
            page=page,
            page_size=PAGE_SIZE,
        )

    def _fetch(self, query: str, cursor, lat: str, lon: str):
        params = [
            {"key": "q", "value": query},
            {"key": "lat", "value": lat},
            {"key": "lon", "value": lon},
            {"key": "radius", "value": "50"},
            {"key": "limit", "value": str(PAGE_SIZE)},
            {"key": "sort", "value": "-posted"},
            {"key": "platform", "value": "web"},
        ]
        if cursor:
            params.append({"key": "page_cursor", "value": cursor})

        resp = self._session.post(
            _GRAPHQL_URL,
            json={"query": _QUERY, "variables": {"searchParams": params}},
            headers={
                "Content-Type": "application/json",
                "User-Agent": _UA,
                "x-ou-operation-name": "GetModularFeed",
                "x-ou-d-token": "web-" + secrets.token_hex(28),
                "x-ou-version": "2026.1.0",
            },
            timeout=15,
        )
        if resp.status_code in (403, 429):
            raise RuntimeError(f"OfferUp blocked the request (HTTP {resp.status_code})")
        resp.raise_for_status()

        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"OfferUp GraphQL error: {data['errors'][0]['message']}")

        feed = data["data"]["modularFeed"]
        listings = []
        for tile in feed.get("looseTiles", []):
            if tile.get("__typename") != "ModularFeedTileListing":
                continue
            l = tile.get("listing") or {}
            img = (l.get("image") or {}).get("url")
            listings.append(
                Listing(
                    id=str(l.get("listingId", "")),
                    title=l.get("title") or "",
                    price=_to_price(l.get("price")),
                    condition=l.get("conditionText"),
                    sold_count=None,
                    image_url=img,
                    url=f"https://offerup.com/item/detail/{l.get('listingId', '')}",
                    snippet=l.get("locationName"),
                )
            )
        return listings, feed.get("pageCursor")

    def _geocode(self, location: str | None) -> tuple[str, str]:
        """Resolve a location string to (lat, lon) via Nominatim. Cached."""
        if not location:
            return "32.7767", "-96.7970"  # Dallas, TX default
        if location in self._geo:
            return self._geo[location]
        resp = self._session.get(
            _NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": _UA},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            raise RuntimeError(f"Could not geocode location: {location}")
        coords = (str(results[0]["lat"]), str(results[0]["lon"]))
        self._geo[location] = coords
        return coords
