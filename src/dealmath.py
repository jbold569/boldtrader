"""Deal math per ADR 0011: fair price, effective price, threshold, verdict.

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

MIN_OBSERVATIONS = 5          # below this, no fair price exists yet (ADR 0011)
FAIR_WINDOW_DAYS = 90
REFINE_MIN_OBSERVATIONS = 30  # volatility refinement waits for a real pool
SURGE_TRIGGER_PCT = 15.0      # ADR 0001: surge starts above +15% ...
SURGE_CLEAR_PCT = 5.0         # ... and clears only below +5%
DEFAULT_THRESHOLD_PCT = 25.0


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


def _iqr_fence(sorted_prices: list[float]) -> list[float]:
    """Drop values beyond Q1 - 1.5*IQR / Q3 + 1.5*IQR (ADR 0001)."""
    q1 = median(sorted_prices[: len(sorted_prices) // 2])
    q3 = median(sorted_prices[(len(sorted_prices) + 1) // 2 :])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [p for p in sorted_prices if lo <= p <= hi]


def refined_threshold(floor_pct: float, pooled_prices: list[float]) -> float:
    """Raise the threshold to the measured noise floor when noise is worse.

    Per ADR 0001: an IQR fence drops extreme listings first, then
    noise = MAD/median as a percentage. The refinement may only RAISE
    the threshold (a noisy market demands a bigger discount to be a
    real deal); it NEVER lowers the configured floor. Below 30
    observations the pool is too thin to measure — cold start, the
    floor stands alone.
    """
    if len(pooled_prices) < REFINE_MIN_OBSERVATIONS:
        return floor_pct
    kept = _iqr_fence(sorted(pooled_prices))
    med = median(kept)
    if med <= 0:
        return floor_pct
    noise_pct = 100.0 * median(abs(p - med) for p in kept) / med
    return max(floor_pct, noise_pct)


def global_threshold(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT value FROM settings WHERE key='deal_threshold'"
    ).fetchone()
    return float(row[0]) if row else DEFAULT_THRESHOLD_PCT


def threshold_for(
    conn: sqlite3.Connection,
    product_identity_id: int,
    as_of: date | None = None,
) -> float:
    """The deal threshold for one identity: its override beats the global,
    then volatility refinement raises it if measured noise demands."""
    row = conn.execute(
        "SELECT deal_threshold FROM product_identities WHERE id=?",
        (product_identity_id,),
    ).fetchone()
    floor_pct = row[0] if row and row[0] is not None else global_threshold(conn)
    pooled = [
        r[0]
        for r in conn.execute(
            "SELECT effective_price FROM price_observations "
            "WHERE product_identity_id=? AND observed_at >= ?",
            (product_identity_id, _window_start(as_of, FAIR_WINDOW_DAYS)),
        )
    ]
    return refined_threshold(floor_pct, pooled)


def deal_verdict(
    effective: float, fair: float | None, threshold_pct: float
) -> str:
    """'deal' iff effective < fair * (1 - threshold/100); 'unknown' if no fair."""
    if fair is None:
        return "unknown"
    line = fair * (1.0 - threshold_pct / 100.0)
    return "deal" if effective < line else "no_deal"


def surge_state(
    recent_median: float | None, prior_median: float | None, previously_surging: bool
) -> bool:
    """Hysteresis on the price surge (ADR 0001).

    Starts above +15% over the prior window, clears only below +5%. The
    gap prevents the flag flapping while prices sit near the trigger.
    """
    if recent_median is None or prior_median is None or prior_median <= 0:
        return False
    rise_pct = 100.0 * (recent_median - prior_median) / prior_median
    if previously_surging:
        return rise_pct >= SURGE_CLEAR_PCT
    return rise_pct > SURGE_TRIGGER_PCT


def detect_surge(
    conn: sqlite3.Connection,
    product_identity_id: int,
    as_of: date | None = None,
    previously_surging: bool = False,
) -> bool:
    """Pooled (all conditions) 30d vs previous 30d median surge check."""
    base = _today(as_of)
    recent_start = (base - timedelta(days=30)).isoformat()
    prior_start = (base - timedelta(days=60)).isoformat()
    recent = [
        r[0]
        for r in conn.execute(
            "SELECT effective_price FROM price_observations "
            "WHERE product_identity_id=? AND observed_at >= ?",
            (product_identity_id, recent_start),
        )
    ]
    prior = [
        r[0]
        for r in conn.execute(
            "SELECT effective_price FROM price_observations "
            "WHERE product_identity_id=? AND observed_at >= ? AND observed_at < ?",
            (product_identity_id, prior_start, recent_start),
        )
    ]
    recent_median = median(recent) if recent else None
    prior_median = median(prior) if prior else None
    return surge_state(recent_median, prior_median, previously_surging)
