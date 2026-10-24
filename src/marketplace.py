"""Marketplace abstraction: the interface every marketplace integration implements."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Listing:
    """One seller's posting of one thing on one marketplace."""

    id: str
    title: str
    price: float | None = None
    condition: str | None = None
    sold_count: int | None = None
    image_url: str | None = None
    url: str = ""
    snippet: str | None = None
    marketplace: str = ""  # stamped by the server after fetch


@dataclass
class ListingDetail:
    """Full record of one Listing for Enrichment: what the search tile omits.

    shipping_cost is None where the marketplace doesn't expose shipping/fees.
    """

    description: str = ""
    images: list[str] = field(default_factory=list)
    shipping_cost: float | None = None


@dataclass
class SearchResult:
    """One page of Listings returned by a Search."""

    listings: list[Listing] = field(default_factory=list)
    total_results: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 0  # 0 = derive from total_results/page_size

    def __post_init__(self) -> None:
        if self.total_pages <= 0:
            if self.total_results <= 0:
                self.total_pages = 1
            else:
                self.total_pages = max(1, math.ceil(self.total_results / self.page_size))


class Marketplace(ABC):
    """A platform where listings appear. Implement search() per platform."""

    name: str = "unknown"

    @abstractmethod
    def search(self, query: str, page: int = 1, location: str | None = None) -> SearchResult:
        """Run a keyword Search and return one page of Listings.

        location is a human place name (city, ZIP, metro). Marketplaces that
        are geo-scoped (OfferUp) require it; keyword-only ones ignore it.
        """

    def fetch_detail(self, listing: Listing) -> ListingDetail:
        """Fetch the full listing record (description, images, shipping/fees).

        Raises on any failure; callers degrade the listing to triage-only
        with "enrichment unavailable". One marketplace never blocks the pipeline.
        """
        raise NotImplementedError(f"{self.name} does not implement fetch_detail")
