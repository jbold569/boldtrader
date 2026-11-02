"""Ticket #73 — daily digest: render, dated file, Signal delivery.

The renderer is a pure function of the SweepReport: every block (per
search, price drops, failed marketplaces, rewritten descriptions,
Facebook session) is asserted straight from a sample report. The file
write always precedes the send attempt; a failing send (fake binary /
fake transport) is logged and leaves the file intact and the caller
unharmed.
"""

from __future__ import annotations

import datetime
import json
import sqlite3

import pytest

from src import digest


def sample_report():
    long_old = "old widget description " * 30  # > 200 chars
    long_new = "new sharper description " * 30
    return {
        "started_at": "2026-11-01T13:00:00+00:00",
        "finished_at": "2026-11-01T13:59:00+00:00",
        "searches": [
            {
                "search_id": 1,
                "summary": "Find X200 laptop",
                "new_listing_count": 12,
                "match_count": 4,
                "failed": False,
                "timed_out": False,
                "best_margin_pct": 23.5,
            },
            {
                "search_id": 2,
                "summary": "GPU under $150",
                "new_listing_count": 0,
                "match_count": 0,
                "failed": True,
                "timed_out": True,
                "error": "timed out after 1200s",
                "best_margin_pct": None,
            },
            {
                "search_id": 3,
                "summary": "ThinkPad T480",
                "new_listing_count": 5,
                "match_count": 2,
                "failed": False,
                "timed_out": False,
                "best_margin_pct": None,
                "old_desc": long_old,
                "new_desc": long_new,
                "evidence_count": 7,
            },
        ],
        "price_refresh": {
            "refreshed_count": 10,
            "failed_count": 2,
            "blocked_marketplaces": {"facebook": 3},
            "price_drops": {
                "count": 5,
                "top_3": [
                    {"listing_id": "ebay:1", "amount": 150.0,
                     "old_effective": 900.0, "new_effective": 750.0},
                    {"listing_id": "offerup:2", "amount": 60.0,
                     "old_effective": 460.0, "new_effective": 400.0},
                    {"listing_id": "ebay:3", "amount": 12.5,
                     "old_effective": 112.5, "new_effective": 100.0},
                ],
            },
        },
        "reresolve": {"moves": [], "total": 8, "moved": 3, "unchanged": 5,
                     "skipped_corrected": 0},
        "enrichment_drained": True,
        "outcome": "partial",
    }


def expected_text():
    return digest.render_digest(sample_report(), facebook_status="session OK")


# --- renderer ----------------------------------------------------------------


def test_render_per_search_block():
    text = expected_text()
    assert "Find X200 laptop" in text
    assert "12 new" in text
    assert "4 matches" in text
    assert "23.5%" in text
    # A search with no computable margin reads n/a, not a crash or a zero.
    assert "best margin n/a" in text


def test_render_price_drop_block():
    text = expected_text()
    assert "Price drops: 5" in text
    assert "ebay:1" in text
    assert "$150.00" in text
    assert "offerup:2" in text
    assert "ebay:3" in text


def test_render_failed_marketplaces_block():
    text = expected_text()
    assert "Failed marketplaces: facebook (3)" in text
    # The timed-out search is surfaced as a failed line too.
    assert "search #2 — timed out after 1200s" in text


def test_render_rewritten_descriptions_old_to_new():
    text = expected_text()
    assert "old: old widget description" in text
    assert "new: new sharper description" in text
    # Trimmed to ~200 chars with an ellipsis, not dumped whole.
    assert "old widget description " * 30 not in text
    long_line = next(l for l in text.splitlines() if "old: old widget" in l)
    assert "..." in long_line
    assert len(long_line) < 260


def test_render_facebook_session_state():
    ok = digest.render_digest(sample_report(), facebook_status="session OK")
    assert "Facebook: session OK" in ok
    bad = digest.render_digest(sample_report(), facebook_status="not logged in")
    assert "Facebook: not logged in" in bad


def test_render_block_order():
    text = expected_text()
    i_searches = text.index("Searches:")
    i_drops = text.index("Price drops:")
    i_failed = text.index("Failed marketplaces:")
    i_desc = text.index("Rewritten descriptions:")
    i_fb = text.index("Facebook:")
    assert i_searches < i_drops < i_failed < i_desc < i_fb


def test_render_empty_sweep_still_renders():
    report = {"started_at": "a", "finished_at": "b", "searches": [],
              "price_refresh": {"refreshed_count": 0, "failed_count": 0,
                               "blocked_marketplaces": {},
                               "price_drops": {"count": 0, "top_3": []}},
              "reresolve": {}, "enrichment_drained": True,
              "outcome": "complete"}
    text = digest.render_digest(report, facebook_status="session OK")
    assert "outcome: complete" in text
    assert "Price drops: 0" in text
    assert "Failed marketplaces: none" in text


# --- facebook session signal ---------------------------------------------------


def test_facebook_logged_in_from_profile_cookies(tmp_path):
    digest.PROFILE_DIR = tmp_path / "missing-profile"
    assert digest.facebook_logged_in() is False

    (tmp_path / "Default").mkdir()
    cpath = tmp_path / "Default" / "Cookies"
    conn = sqlite3.connect(str(cpath))
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
    conn.execute("INSERT INTO cookies VALUES ('.facebook.com', 'datr')")
    conn.commit()
    conn.close()
    digest.PROFILE_DIR = tmp_path
    assert digest.facebook_logged_in() is False  # datr only: anonymous

    conn = sqlite3.connect(str(cpath))
    conn.execute("INSERT INTO cookies VALUES ('.facebook.com', 'c_user')")
    conn.commit()
    conn.close()
    assert digest.facebook_logged_in() is True


# --- write-before-send ordering + failure containment --------------------------


def test_deliver_writes_file_before_send(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(digest, "facebook_logged_in", lambda: True)
    seen = {}

    def fake_send(text):
        path = tmp_path / "2026-11-01.md"
        seen["existed_at_send_time"] = path.exists()
        seen["content_at_send_time"] = path.read_text() if path.exists() else None

    monkeypatch.setattr(digest, "send_signal", fake_send)
    path = digest.deliver_digest(sample_report(), date=datetime.date(2026, 11, 1))
    assert str(path).endswith("2026-11-01.md")
    assert seen["existed_at_send_time"] is True
    assert seen["content_at_send_time"] == path.read_text()
    assert seen["content_at_send_time"] == expected_text()


def test_send_failure_file_still_lands_and_is_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(digest, "facebook_logged_in", lambda: True)

    def exploding_send(text):
        raise RuntimeError("signal-cli not found")

    monkeypatch.setattr(digest, "send_signal", exploding_send)
    with caplog.at_level("WARNING"):
        path = digest.deliver_digest(sample_report(), date=datetime.date(2026, 11, 2))
    # deliver_digest swallows the failure: no exception escapes.
    assert path.exists()
    assert path.read_text() == expected_text()
    assert path.stat().st_size > 0
    assert "signal send failed" in caplog.text
    assert "signal-cli not found" in caplog.text


# --- send_signal transport -----------------------------------------------------


def test_send_signal_payload_and_short_timeout(monkeypatch):
    calls = {}

    class FakeResp:
        def read(self):
            return json.dumps({"jsonrpc": "2.0", "result": {"timestamp": 1}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls["body"] = json.loads(req.data.decode())
        calls["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(digest.urllib.request, "urlopen", fake_urlopen)
    digest.send_signal("hello digest")
    assert calls["body"]["method"] == "send"
    assert calls["body"]["params"]["recipient"] == [digest.SIGNAL_ACCOUNT]
    assert calls["body"]["params"]["message"] == "hello digest"
    assert calls["timeout"] == digest.SEND_TIMEOUT_SECONDS
    assert 0 < digest.SEND_TIMEOUT_SECONDS <= 10  # short: no wedged-CLI hang


def test_send_signal_rejects_error_response(monkeypatch):
    class FakeResp:
        def read(self):
            return json.dumps(
                {"jsonrpc": "2.0", "error": {"code": -1, "message": "boom"}}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        digest.urllib.request, "urlopen", lambda req, timeout=None: FakeResp()
    )
    with pytest.raises(RuntimeError):
        digest.send_signal("nope")
