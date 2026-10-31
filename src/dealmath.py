"""Deal math per ADR 0011: fair price and effective price.

Why this is a separate module: every consumer of deal quality (cards, the
deals endpoint, MCP tools) must agree on one arithmetic, and the numbers
only mean something once there are enough of them. Fair price is the
median of the trailing 90-day price observations for one
(identity, condition) pair — medians survive the outlier listings that
poison averages on used marketplaces. Below five observations nothing is
"fair": the verdict is unknown rather than a confident guess on an empty
sample.

All money is float USD; all dates are ISO date strings ("YYYY-MM-DD"),
which sort lexicographically and make the window predicates plain SQL.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from statistics import median

MIN_OBSERVATIONS = 5  # below this, no fair price exists yet (ADR 0011)
FAIR_WINDOW_DAYS = 90


def _today(as_of: date | None) -> date:
    return as_of if as_of is not None else date.today()


def _window_start(as_of: date | None, days: int) -> str:
    return (_today(as_of) - timedelta(days=days)).isoformat()


def record_observation(
    conn: sqlite3.Connection,
    listing_id: str,
    product_identity_id: int,
    condition: str,
    effective_price: float,
    observed_at: str | None = None,
) -> None:
    """Append one price observation. Commit is the caller's."""
    conn.execute(
        "INSERT INTO price_observations "
        "(listing_id, product_identity_id, condition, effective_price, observed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            listing_id,
            product_identity_id,
            condition,
            effective_price,
            observed_at or _today(None).isoformat(),
        ),
    )


def fair_price(
    conn: sqlite3.Connection,
    product_identity_id: int,
    condition: str,
    as_of: date | None = None,
) -> float | None:
    """Median effective price of the trailing 90-day window, or None.

    None means cold start: fewer than MIN_OBSERVATIONS in the window, so
    the sample cannot support a "fair" claim yet (ADR 0011).
    """
    rows = conn.execute(
        "SELECT effective_price FROM price_observations "
        "WHERE product_identity_id=? AND condition=? AND observed_at >= ?",
        (product_identity_id, condition, _window_start(as_of, FAIR_WINDOW_DAYS)),
    ).fetchall()
    prices = [r[0] for r in rows]
    if len(prices) < MIN_OBSERVATIONS:
        return None
    return float(median(prices))


def effective_price(
    asking_price: float, shipping_cost: float | None, flip_value: float
) -> float:
    """Out-the-door price minus the flip value of the extras.

    Missing shipping (marketplaces that never expose it) counts as zero:
    the buyer still pays the asking price at the door.
    """
    out_the_door = asking_price + (shipping_cost or 0.0)
    return out_the_door - flip_value


def component_is_inside(component_description: str, identity_description: str) -> bool:
    """True if the component is already part of the identity's own prose.

    Substring match, case-insensitive: "8GB RAM" inside "...with 8GB RAM
    and 256GB SSD" means the component is the product itself, not a flip.
    """
    return component_description.strip().lower() in identity_description.strip().lower()


def flip_value(
    conn: sqlite3.Connection,
    bundle: list[dict],
    identity_description: str,
    as_of: date | None = None,
) -> float:
    """Sum of fair asks for bundle components that are NOT inside the item.

    A component only contributes when its own identity resolves AND has a
    fair price; anything unresolvable contributes zero — we never pad the
    flip with a guess (ticket #54).
    """
    total = 0.0
    for item in bundle:
        # Pre-#53 corpora stored bundles as bare strings; a string is the
        # component description itself.
        if isinstance(item, str):
            description = item.strip()
        else:
            description = (item.get("description") or "").strip()
        if not description:
            continue
        if component_is_inside(description, identity_description):
            continue
        row = conn.execute(
            "SELECT id FROM product_identities WHERE description=?",
            (description,),
        ).fetchone()
        if row is None:
            continue
        price = fair_price(conn, row[0], "complete", as_of=as_of)
        if price is None:
            continue
        total += price
    return total


