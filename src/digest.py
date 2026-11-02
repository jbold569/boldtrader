"""Daily digest (ticket #73): the morning message.

The SweepReport is rendered to plain text — per-search numbers, price
drops, failed marketplaces, rewritten identity descriptions, Facebook
session state — written to a dated file under sweeps/ FIRST, then pushed
to the operator's Signal number. The file is the record: if the send
fails for any reason (binary missing, non-zero exit, timeout) the failure
is logged and everything else stands untouched.

Delivery rides the signal-cli daemon's JSON-RPC HTTP endpoint
(127.0.0.1:8120). Verified 2026-11-01: the daemon holds a config lock,
so a direct `signal-cli send` blocks forever ("Config file is in use by
another instance") while a second one is running; the HTTP RPC path is
the shape that actually works against a live daemon.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request
from datetime import date as _date
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DIGEST_DIR = REPO_ROOT / "sweeps"
SIGNAL_ACCOUNT = "+18179371709"
SIGNAL_HTTP_URL = "http://127.0.0.1:8120/api/v1/rpc"
# A wedged daemon must not hang the sweep tail.
SEND_TIMEOUT_SECONDS = 10
# Old/new description lines are trimmed to this for readability.
DESC_PREVIEW_CHARS = 200

PROFILE_DIR = REPO_ROOT / ".fb-profile"


def facebook_logged_in() -> bool:
    """Facebook session state, read from the persistent Playwright profile.

    c_user is the logged-in identity cookie: its presence means the
    profile holds an authenticated session (the same check
    src/facebook_scraper.login uses to confirm a successful login); its
    absence means anonymous or expired.

    shortcut: presence-only. A stale-but-present c_user after an FB-side
    logout reads as logged in; if that bites in practice, upgrade to a
    live page check (liveness._fb_session_ok)."""
    cookie_db = PROFILE_DIR / "Default" / "Cookies"
    if not cookie_db.exists():
        return False
    conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT 1 FROM cookies WHERE name='c_user' LIMIT 1"
        ).fetchone() is not None
    finally:
        conn.close()


def _trim(text: str) -> str:
    if len(text) <= DESC_PREVIEW_CHARS:
        return text
    return text[:DESC_PREVIEW_CHARS] + "..."


def render_digest(report: dict, facebook_status: str) -> str:
    """Pure function of the SweepReport plus the Facebook session line.

    Blocks in order: per-search numbers, price drops, failed
    marketplaces, rewritten descriptions, Facebook state."""
    lines = [
        f"Daily Sweep {report.get('started_at', '')} — "
        f"outcome: {report.get('outcome', '?')}"
    ]

    lines.append("")
    lines.append("Searches:")
    for s in report.get("searches", []):
        margin = s.get("best_margin_pct")
        margin_txt = f"{margin:.1f}%" if margin is not None else "n/a"
        summary = s.get("summary") or f"#{s.get('search_id', '?')}"
        lines.append(
            f"- {summary}: {s.get('new_listing_count', 0)} new, "
            f"{s.get('match_count', 0)} matches, best margin {margin_txt}"
        )
    if not report.get("searches"):
        lines.append("- none")

    price_refresh = report.get("price_refresh") or {}
    drops = price_refresh.get("price_drops") or {}
    lines.append("")
    lines.append(f"Price drops: {drops.get('count', 0)}")
    for d in drops.get("top_3") or []:
        lines.append(
            f"- {d['listing_id']}: -${d['amount']:.2f} "
            f"(${d['old_effective']:.2f} -> ${d['new_effective']:.2f})"
        )

    lines.append("")
    blocked = price_refresh.get("blocked_marketplaces") or {}
    parts = [f"{name} ({count})" for name, count in blocked.items()]
    lines.append(
        "Failed marketplaces: " + (", ".join(parts) if parts else "none")
    )
    for s in report.get("searches", []):
        if s.get("failed"):
            reason = s.get("error") or "failed"
            lines.append(f"- search #{s.get('search_id', '?')} — {reason}")

    lines.append("")
    lines.append("Rewritten descriptions:")
    rewrote = [s for s in report.get("searches", []) if "new_desc" in s]
    if not rewrote:
        lines.append("- none")
    for s in rewrote:
        lines.append(f"- search #{s.get('search_id', '?')}")
        lines.append(f"  old: {_trim(s.get('old_desc') or '')}")
        lines.append(f"  new: {_trim(s['new_desc'])}")

    lines.append("")
    lines.append(f"Facebook: {facebook_status}")
    return "\n".join(lines)


def write_digest_file(text: str, when: _date) -> Path:
    """Write the digest to sweeps/YYYY-MM-DD.md. Returns the path."""
    path = DIGEST_DIR / f"{when.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def send_signal(text: str) -> None:
    """Push the text to the operator via the signal-cli daemon's JSON-RPC.

    Raises on any failure: unwritable endpoint, rejected send, timeout.
    The caller (deliver_digest) contains it."""
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "send",
            "params": {"recipient": [SIGNAL_ACCOUNT], "message": text},
        }
    ).encode()
    req = urllib.request.Request(
        SIGNAL_HTTP_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=SEND_TIMEOUT_SECONDS) as resp:
        body = json.loads(resp.read().decode())
    if "error" in body:
        raise RuntimeError(f"signal rejected the send: {body['error']}")


def deliver_digest(report: dict, date: _date | None = None) -> Path:
    """Render, write the dated file, then attempt the Signal push.

    The write happens before the send is attempted, always. The send is
    best-effort: a failure is logged and the file stays as the record.
    Returns the path of the written file."""
    when = date if date is not None else _date.today()
    status = "session OK" if facebook_logged_in() else "not logged in"
    text = render_digest(report, status)
    path = write_digest_file(text, when)
    try:
        send_signal(text)
    except Exception as exc:
        log.warning("signal send failed: %s", exc)
    return path
