"""Night-scoped stale union (ticket #69).

Every Product Identity description rewrite marks the listings judged
under the old words as Stale verdicts. The per-search stale_lids column
cannot hold that history: fan-out wipes it at each start. This module
keeps the running union in its own table — a set of listing ids keyed by
PRIMARY KEY, so duplicates across rewrite events collapse on insert.

Listings carrying a Correction are filtered out at read (construction
of the union view), not at append: user truth outranks description drift
(GLOSSARY: Stale verdict). The read set feeds the reresolve-by-ids path
directly. Clearing the table at the end of the sweep belongs to the Daily
Sweep ticket (#62), not this one.
"""

from __future__ import annotations

import sqlite3

# Corrected enrichments: corrected=1 rides the enriched rows (see
# api.correct_enrichment / enhanced.restore_correction).
_CORRECTED_SQL = (
    "SELECT listing_id FROM enrichments WHERE corrected=1 AND status='enriched'"
)


def record_stale(conn: sqlite3.Connection, lids) -> None:
    """Append this rewrite's stale listing ids to the night's union.
    INSERT OR IGNORE: the primary key IS the set-semantics dedupe."""
    conn.executemany(
        "INSERT OR IGNORE INTO stale_union (listing_id) VALUES (?)",
        [(lid,) for lid in lids],
    )


def read_stale_union(conn: sqlite3.Connection) -> set[str]:
    """The union as one de-duplicated set, corrected listings filtered
    out at construction."""
    return {
        r[0]
        for r in conn.execute(
            f"SELECT listing_id FROM stale_union "
            f"WHERE listing_id NOT IN ({_CORRECTED_SQL})"
        )
    }
