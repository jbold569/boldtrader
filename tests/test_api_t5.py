"""Contract tests for the T5 JSON API surface (ticket #56).

Product Identity CRUD + merge + retune, GET /deals, GET/PATCH /settings,
POST /searches/{id}/run, DELETE /searches/{id}/rejections/{lid}, and
PATCH /enrichments/{lid} (Correction), plus the changed max_price
semantics (effective price, not asking). Same live-server + temp-DB
pattern as the other API tests; the model is always faked.
"""

from __future__ import annotations

import json
import sqlite3
import time
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import router
from src.db import init_db

API = "/api/v1"

IDENTITY_KEYS = {
    "id",
    "description",
    "deal_threshold",
    "synthesized_at",
    "created_at",
    "updated_at",
}

DEAL_ITEM_KEYS = {
    "listing_id",
    "title",
    "url",
    "asking_price",
    "marketplace",
    "image_url",
    "condition",
    "shipping",
    "fair_price",
    "margin_pct",
    "n_observations",
}

CORRECTION_KEYS = {
    "listing_id",
    "product",
    "condition",
    "bundle",
    "corrected",
    "status",
}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB; nothing external."""
    path = tmp_path / "t5.db"
    monkeypatch.setenv("BOLDTRADER_DB", str(path))
    init_db(path).close()

    from src import server as server_mod

    server_mod.Handler.marketplaces = {}
    server_mod.Handler.fanout_marketplaces = {}
    server_mod.Handler.default_market = "offerup"
    server_mod.Handler.cache = server_mod._Cache(60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def db(tmp_path):
    """The same temp DB the server reads, for seeding and asserting."""
    conn = sqlite3.connect(str(tmp_path / "t5.db"))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def call(method: str, url: str, body=None, raw: bytes | None = None):
    """One HTTP round-trip; returns (status, parsed_json_or_None, headers)."""
    data = raw if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else b""
    )
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else None), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return exc.code, parsed, dict(exc.headers)


def seed_identity(conn, description="HP Z440 workstation", deal_threshold=None,
                 synthesized_at=None):
    cur = conn.execute(
        "INSERT INTO product_identities (description, deal_threshold, synthesized_at) "
        "VALUES (?, ?, ?)",
        (description, deal_threshold, synthesized_at),
    )
    conn.commit()
    return cur.lastrowid


def seed_listing(conn, lid, price=100.0, marketplace="offerup", availability="live",
                shipping=None, identity_id=None, condition="used"):
    raw = {
        "id": lid,
        "title": f"Listing {lid}",
        "price": price,
        "condition": condition,
        "url": f"https://example.invalid/{lid}",
        "image_url": f"https://img.invalid/{lid}.jpg",
        "marketplace": marketplace,
    }
    conn.execute(
        "INSERT INTO listings (id, raw, availability, shipping_cost, product_identity_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (lid, json.dumps(raw), availability, shipping, identity_id),
    )
    conn.commit()


def seed_enrichment(conn, lid, description="HP Z440 workstation", matched_id=1,
                   condition="complete", bundle=None, status="enriched",
                   corrected=0):
    product = {
        "description": description,
        "action": "match",
        "matched_id": matched_id,
        "confidence": "high",
    }
    conn.execute(
        "INSERT INTO enrichments (listing_id, product, condition, bundle, confidence, "
        "status, corrected) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            lid,
            json.dumps(product),
            condition,
            json.dumps(bundle if bundle is not None else []),
            json.dumps("high"),
            status,
            corrected,
        ),
    )
    conn.commit()


def seed_obs(conn, lid, pid, condition, prices, day="2026-10-29"):
    # price_observations has a FK on listing_id; obs-only lids need a stub.
    conn.execute(
        "INSERT OR IGNORE INTO listings (id, raw) VALUES (?, ?)",
        (lid, json.dumps({"id": lid})),
    )
    for p in prices:
        conn.execute(
            "INSERT INTO price_observations "
            "(listing_id, product_identity_id, condition, effective_price, observed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (lid, pid, condition, float(p), day),
        )
    conn.commit()

def seed_search(conn, identity_id=None, listing_ids=None, exclusions=None,
               version=1, status="complete", location="Kenmore, WA"):
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, location, "
        "product_identity_id, listing_ids, exclusions, version, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "test search",
            "thing",
            location,
            identity_id,
            json.dumps(listing_ids or {}),
            json.dumps(exclusions or []),
            version,
            status,
        ),
    )
    conn.commit()
    return cur.lastrowid


# --- Product Identities: list / get -----------------------------------------


def test_identity_list_envelope(site, db):
    seed_identity(db, "one")
    seed_identity(db, "two")
    status, body, _ = call("GET", site + "/api/v1/product-identities")
    assert status == 200
    assert set(body) == {"items", "page", "per_page", "total", "total_pages"}
    assert body["total"] == 2
    assert body["total_pages"] == 1
    assert set(body["items"][0]) == IDENTITY_KEYS


def test_identity_list_pagination(site, db):
    for i in range(3):
        seed_identity(db, f"identity {i}")
    status, body, _ = call("GET", site + "/api/v1/product-identities?page=2&per_page=1")
    assert status == 200
    assert body["page"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["description"] == "identity 1"


def test_identity_list_per_page_capped(site):
    _, body, _ = call("GET", site + "/api/v1/product-identities?per_page=500")
    assert body["per_page"] == 200


def test_get_identity(site, db):
    iid = seed_identity(db, "HP Z440", deal_threshold=18.0,
                       synthesized_at="2026-10-20T09:15:00Z")
    status, body, _ = call("GET", f"{site}/api/v1/product-identities/{iid}")
    assert status == 200
    assert set(body) == IDENTITY_KEYS
    assert body["description"] == "HP Z440"
    assert body["deal_threshold"] == 18.0
    # identity._now() writes Z-form already; it must pass through untouched.
    assert body["synthesized_at"] == "2026-10-20T09:15:00Z"


def test_get_identity_missing(site):
    status, body, _ = call("GET", f"{site}/api/v1/product-identities/999")
    assert status == 404
    assert body["error"]["code"] == "identity_not_found"
    assert set(body["error"]) == {"code", "message"}


def test_get_identity_non_integer_id(site):
    status, body, _ = call("GET", f"{site}/api/v1/product-identities/abc")
    assert status == 404
    assert body["error"]["code"] == "identity_not_found"


# --- Product Identities: PATCH ----------------------------------------------


def test_patch_description(site, db):
    iid = seed_identity(db, "old words")
    status, body, _ = call("PATCH", f"{site}/api/v1/product-identities/{iid}",
                          {"description": "new words"})
    assert status == 200
    assert body["description"] == "new words"
    row = db.execute(
        "SELECT description, updated_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row[0] == "new words"


def test_patch_deal_threshold(site, db):
    iid = seed_identity(db)
    _, body, _ = call("PATCH", f"{site}/api/v1/product-identities/{iid}",
                     {"deal_threshold": 30.0})
    assert body["deal_threshold"] == 30.0


def test_patch_clear_deal_threshold(site, db):
    iid = seed_identity(db, deal_threshold=18.0)
    _, body, _ = call("PATCH", f"{site}/api/v1/product-identities/{iid}",
                     {"deal_threshold": None})
    assert body["deal_threshold"] is None
    stored = db.execute(
        "SELECT deal_threshold FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert stored is None


def test_patch_empty_description_rejected(site, db):
    iid = seed_identity(db)
    status, body, _ = call("PATCH", f"{site}/api/v1/product-identities/{iid}",
                          {"description": "   "})
    assert status == 422
    assert body["error"]["code"] == "invalid_identity"


def test_patch_bad_threshold_rejected(site, db):
    iid = seed_identity(db)
    for bad in (0, -5, "cheap", True):
        status, body, _ = call("PATCH", f"{site}/api/v1/product-identities/{iid}",
                              {"deal_threshold": bad})
        assert status == 422, bad
        assert body["error"]["code"] == "invalid_identity"


def test_patch_identity_missing(site):
    status, body, _ = call("PATCH", f"{site}/api/v1/product-identities/999",
                          {"description": "whatever"})
    assert status == 404
    assert body["error"]["code"] == "identity_not_found"


def test_patch_malformed_body(site, db):
    iid = seed_identity(db)
    status, body, _ = call("PATCH", f"{site}/api/v1/product-identities/{iid}",
                          raw=b"{not json")
    assert status == 400
    assert body["error"]["code"] == "malformed_request"


# --- Merge -------------------------------------------------------------------


def seed_merge_world(db):
    """Loser owns a listing, an observation, and a mapped search."""
    loser = seed_identity(db, "loser description")
    winner = seed_identity(db, "winner description")
    seed_listing(db, "l1", identity_id=loser)
    seed_listing(db, "l2", identity_id=loser)
    seed_obs(db, "l1", loser, "complete", [100.0] * 5)
    sid = seed_search(db, identity_id=loser)
    return loser, winner, sid


def test_merge_repoints_everything(site, db):
    loser, winner, sid = seed_merge_world(db)
    # sentinel far in the past so a real bump is unmistakable
    db.execute(
        "UPDATE product_identities SET updated_at='2000-01-01 00:00:00' WHERE id=?",
        (winner,),
    )
    db.commit()
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{loser}/merge",
                          {"into": winner})
    assert status == 200
    assert body["id"] == winner
    assert body["description"] == "winner description"
    rows = db.execute(
        "SELECT product_identity_id FROM listings ORDER BY id"
    ).fetchall()
    assert rows == [(winner,), (winner,)]
    assert db.execute(
        "SELECT DISTINCT product_identity_id FROM price_observations"
    ).fetchall() == [(winner,)]
    assert db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone() == (winner,)
    assert db.execute(
        "SELECT COUNT(*) FROM product_identities WHERE id=?", (loser,)
    ).fetchone() == (0,)
    bumped = db.execute(
        "SELECT updated_at FROM product_identities WHERE id=?", (winner,)
    ).fetchone()[0]
    assert bumped != "2000-01-01 00:00:00"


def test_merge_missing_into(site, db):
    loser, _winner = seed_merge_world(db)[:2]
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{loser}/merge", {})
    assert status == 400
    assert body["error"]["code"] == "invalid_merge"


def test_merge_into_non_integer(site, db):
    loser = seed_merge_world(db)[0]
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{loser}/merge",
                          {"into": "two"})
    assert status == 422
    assert body["error"]["code"] == "invalid_merge"


def test_merge_into_self_rejected(site, db):
    loser = seed_merge_world(db)[0]
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{loser}/merge",
                          {"into": loser})
    assert status == 422
    assert body["error"]["code"] == "invalid_merge"


def test_merge_loser_missing(site, db):
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/999/merge",
                          {"into": 1})
    assert status == 404
    assert body["error"]["code"] == "identity_not_found"


def test_merge_winner_missing(site, db):
    loser = seed_merge_world(db)[0]
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{loser}/merge",
                          {"into": 999})
    assert status == 404
    assert body["error"]["code"] == "identity_not_found"


def test_merge_rolls_back_when_the_delete_fails(site, db, monkeypatch):
    from src import api as api_mod

    loser, _winner, sid = seed_merge_world(db)
    real_get_connection = api_mod.get_connection

    class Boom:
        """Passes everything through except the loser delete."""

        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if "DELETE FROM product_identities" in sql:
                raise RuntimeError("forced mid-transaction failure")
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def flaky(*args, **kwargs):
        return Boom(real_get_connection(*args, **kwargs))

    monkeypatch.setattr(api_mod, "get_connection", flaky)
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{loser}/merge",
                          {"into": 999 if False else _winner})
    assert status == 500
    assert body["error"]["code"] == "merge_failed"

    # Nothing changed: children still point at the loser, loser still exists.
    rows = db.execute("SELECT product_identity_id FROM listings ORDER BY id").fetchall()
    assert rows == [(loser,), (loser,)]
    assert db.execute(
        "SELECT product_identity_id FROM price_observations"
    ).fetchall() == [(loser,)] * 5
    assert db.execute(
        "SELECT product_identity_id FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone() == (loser,)
    assert db.execute(
        "SELECT COUNT(*) FROM product_identities WHERE id=?", (loser,)
    ).fetchone() == (1,)


# --- Retune -------------------------------------------------------------------


class Recorder:
    def __init__(self, reply="Retuned description."):
        self.reply = reply
        self.calls = []

    def __call__(self, evidence, model=None):
        self.calls.append(evidence)
        return self.reply


def test_retune_persists_new_description(site, db, monkeypatch):
    iid = seed_identity(db, "old description", deal_threshold=18.0,
                       synthesized_at="2026-10-01 00:00:00")
    seed_listing(db, "m", price=100.0)
    sid = seed_search(db, identity_id=iid, listing_ids={"m": "match"})
    rec = Recorder(reply="Retuned description.")
    monkeypatch.setattr(router, "synthesize_description", rec)

    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{iid}/retune")
    assert status == 200
    assert body["description"] == "Retuned description."
    assert body["synthesized_at"] is not None
    row = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row[0] == "Retuned description."
    stale = db.execute(
        "SELECT stale_lids FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert set(json.loads(stale)) == {"m"}
    assert rec.calls[0]["mode"] == "retune"
    assert rec.calls[0]["deal_threshold"] == 18.0


def test_retune_first_run_synthesizes(site, db, monkeypatch):
    iid = seed_identity(db, "a seed phrase")  # synthesized_at NULL
    seed_listing(db, "m", price=100.0)
    seed_search(db, identity_id=iid, listing_ids={"m": "match"})
    rec = Recorder(reply="A synthesized description.")
    monkeypatch.setattr(router, "synthesize_description", rec)

    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{iid}/retune")
    assert status == 200
    assert body["description"] == "A synthesized description."
    assert rec.calls[0]["mode"] == "synthesize"
    assert rec.calls[0]["rejects"] == []


def test_retune_unchanged_description_is_noop(site, db, monkeypatch):
    iid = seed_identity(db, "same text", synthesized_at="2026-10-01 00:00:00")
    seed_listing(db, "m", price=100.0)
    sid = seed_search(db, identity_id=iid, listing_ids={"m": "match"})
    monkeypatch.setattr(router, "synthesize_description",
                       Recorder(reply="same text"))
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{iid}/retune")
    assert status == 200
    assert body["description"] == "same text"
    stale = db.execute(
        "SELECT stale_lids FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()[0]
    assert json.loads(stale) == []


def test_retune_synthesis_failure_is_500(site, db, monkeypatch):
    iid = seed_identity(db, "old", synthesized_at="2026-10-01 00:00:00")
    seed_listing(db, "m", price=100.0)
    seed_search(db, identity_id=iid, listing_ids={"m": "match"})

    def boom(evidence, model=None):
        raise router.RouterError("router down")

    monkeypatch.setattr(router, "synthesize_description", boom)
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/{iid}/retune")
    assert status == 500
    assert body["error"]["code"] == "synthesis_failed"
    row = db.execute(
        "SELECT description, synthesized_at FROM product_identities WHERE id=?", (iid,)
    ).fetchone()
    assert row == ("old", "2026-10-01 00:00:00")


def test_retune_missing_identity(site):
    status, body, _ = call("POST", f"{site}/api/v1/product-identities/999/retune")
    assert status == 404
    assert body["error"]["code"] == "identity_not_found"


# --- GET /deals ---------------------------------------------------------------


def seed_deals(db):
    """identity 1: fair price 200 (five obs). Two deal listings, one no-deal."""
    pid = seed_identity(db, "HP Z440 workstation")
    seed_obs(db, "obs1", pid, "complete", [150.0, 200.0, 220.0, 180.0, 200.0])
    # deal: effective 130 < 200 * 0.75 = 150
    seed_listing(db, "deal1", price=120.0, shipping=10.0, identity_id=pid,
                marketplace="offerup")
    seed_enrichment(db, "deal1", condition="complete")
    # no deal: effective 170 > 150
    seed_listing(db, "no1", price=170.0, shipping=0.0, identity_id=pid,
                marketplace="facebook")
    seed_enrichment(db, "no1", condition="complete")
    return pid


def test_deals_only_lists_verdict_deals(site, db):
    seed_deals(db)
    status, body, _ = call("GET", site + "/api/v1/deals")
    assert status == 200
    items = body["items"]
    assert [i["listing_id"] for i in items] == ["deal1"]
    assert body["total"] == 1


def test_deals_item_shape(site, db):
    seed_deals(db)
    _, body, _ = call("GET", site + "/api/v1/deals")
    item = body["items"][0]
    assert set(item) == DEAL_ITEM_KEYS
    assert item["asking_price"] == 120.0
    assert item["shipping"] == 10.0
    assert item["condition"] == "complete"
    assert item["fair_price"] == 200.0
    assert item["n_observations"] == 5
    # (200 - 130) / 200 * 100
    assert item["margin_pct"] == 35.0


def test_deals_cold_start_excluded(site, db):
    pid = seed_identity(db, "cold identity")  # no observations: no fair price
    seed_listing(db, "cold", price=10.0, shipping=0.0, identity_id=pid)
    seed_enrichment(db, "cold", condition="complete")
    _, body, _ = call("GET", site + "/api/v1/deals")
    assert body["items"] == []


def test_deals_filter_by_identity(site, db):
    pid = seed_deals(db)
    other = seed_identity(db, "other identity")
    seed_obs(db, "obs2", other, "complete", [900.0] * 5)
    seed_listing(db, "d2", price=100.0, shipping=0.0, identity_id=other)
    seed_enrichment(db, "d2", condition="complete", matched_id=other)
    _, body, _ = call("GET",
                     site + f"/api/v1/deals?product_identity_id={pid}")
    assert [i["listing_id"] for i in body["items"]] == ["deal1"]
    _, body, _ = call("GET",
                     site + f"/api/v1/deals?product_identity_id={other}")
    assert [i["listing_id"] for i in body["items"]] == ["d2"]


def test_deals_filter_by_marketplace_and_availability(site, db):
    seed_deals(db)
    _, body, _ = call("GET", site + "/api/v1/deals?marketplace=offerup")
    assert [i["listing_id"] for i in body["items"]] == ["deal1"]
    _, body, _ = call("GET", site + "/api/v1/deals?marketplace=facebook")
    assert body["items"] == []
    db.execute("UPDATE listings SET availability='dead' WHERE id='deal1'")
    db.commit()
    _, body, _ = call("GET", site + "/api/v1/deals?availability=dead")
    assert [i["listing_id"] for i in body["items"]] == ["deal1"]
    _, body, _ = call("GET", site + "/api/v1/deals?availability=live")
    assert body["items"] == []


def test_deals_max_price_filters_effective(site, db):
    seed_deals(db)  # deal1 effective = 130.0
    _, body, _ = call("GET", site + "/api/v1/deals?max_price=140")
    assert [i["listing_id"] for i in body["items"]] == ["deal1"]
    _, body, _ = call("GET", site + "/api/v1/deals?max_price=125")
    assert body["items"] == []


def test_deals_sort_margin_desc(site, db):
    pid = seed_deals(db)  # deal1 margin 35.0
    rich = seed_identity(db, "rich deal identity")
    seed_obs(db, "obs3", rich, "complete", [900.0] * 5)
    seed_listing(db, "d3", price=100.0, shipping=0.0, identity_id=rich)
    seed_enrichment(db, "d3", condition="complete", matched_id=rich)
    _, body, _ = call("GET", site + "/api/v1/deals")
    margins = [i["margin_pct"] for i in body["items"]]
    assert margins == sorted(margins, reverse=True)
    assert body["items"][0]["listing_id"] == "d3"


def test_deals_bad_sort_400(site):
    status, body, _ = call("GET", site + "/api/v1/deals?sort=newest")
    assert status == 400
    assert body["error"]["code"] == "invalid_sort"


def test_deals_bad_max_price_400(site):
    status, body, _ = call("GET", site + "/api/v1/deals?max_price=cheap")
    assert status == 400
    assert body["error"]["code"] == "invalid_max_price"


def test_deals_bad_availability_400(site):
    status, body, _ = call("GET", site + "/api/v1/deals?availability=someways")
    assert status == 400
    assert body["error"]["code"] == "invalid_availability"


# --- Settings -----------------------------------------------------------------


def test_get_settings_default(site):
    status, body, _ = call("GET", site + "/api/v1/settings")
    assert status == 200
    assert body == {"deal_threshold": 25.0}


def test_patch_settings_roundtrip(site):
    status, body, _ = call("PATCH", site + "/api/v1/settings",
                          {"deal_threshold": 30})
    assert status == 200
    assert body["deal_threshold"] == 30.0
    _, body, _ = call("GET", site + "/api/v1/settings")
    assert body["deal_threshold"] == 30.0


def test_patch_settings_rejects_bad_values(site):
    for bad in (0, -3, "wide", True):
        status, body, _ = call("PATCH", site + "/api/v1/settings",
                              {"deal_threshold": bad})
        assert status == 422, bad
        assert body["error"]["code"] == "invalid_settings"


def test_patch_settings_rejects_unknown_key(site):
    status, body, _ = call("PATCH", site + "/api/v1/settings", {"mystery": 1})
    assert status == 422
    assert body["error"]["code"] == "invalid_settings"


def test_patch_settings_preserves_other_rows(site, db):
    db.execute("INSERT INTO settings (key, value) VALUES ('other', 'kept')")
    db.commit()
    _, body, _ = call("PATCH", site + "/api/v1/settings", {"deal_threshold": 12})
    assert body["deal_threshold"] == 12.0
    assert db.execute(
        "SELECT value FROM settings WHERE key='other'"
    ).fetchone() == ("kept",)


# --- POST /searches/{id}/run ---------------------------------------------------


def test_run_search_kicks_fanout_without_version_bump(site, db, monkeypatch):
    recorded = []

    def fake_fan_out(marketplaces, search_id, location=None):
        recorded.append((search_id, location))

    monkeypatch.setattr("src.api.fan_out", fake_fan_out)
    sid = seed_search(db, version=3)

    status, body, _ = call("POST", f"{site}/api/v1/searches/{sid}/run")
    assert status == 202
    assert body["id"] == sid
    assert body["version"] == 3
    # The kick is async; poll briefly rather than sleep a fixed amount.
    deadline = time.time() + 2.0
    while not recorded and time.time() < deadline:
        time.sleep(0.01)
    assert recorded == [(sid, "Kenmore, WA")]


def test_run_search_missing(site):
    status, body, _ = call("POST", f"{site}/api/v1/searches/999/run")
    assert status == 404
    assert body["error"]["code"] == "search_not_found"


# --- DELETE /searches/{id}/rejections/{listing_id} ----------------------------


def test_restore_rejection(site, db):
    iid = seed_identity(db, "HP Z440 workstation")
    seed_listing(db, "r1", price=100.0)
    sid = seed_search(db, identity_id=iid, listing_ids={"r1": "not_match"},
                     exclusions=["wrong brand"])
    db.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, 'r1', 'wrong brand')",
        (sid,),
    )
    db.execute(
        "UPDATE bargain_searches SET stale_lids=? WHERE id=?",
        (json.dumps(["r1"]), sid),
    )
    db.commit()

    status, body, _ = call("DELETE",
                          f"{site}/api/v1/searches/{sid}/rejections/r1")
    assert status == 200
    assert body["id"] == sid
    assert body["exclusions"] == []
    row = db.execute(
        "SELECT listing_ids, stale_lids FROM bargain_searches WHERE id=?", (sid,)
    ).fetchone()
    assert json.loads(row[0])["r1"] == "match"
    assert json.loads(row[1]) == []
    assert db.execute(
        "SELECT COUNT(*) FROM rejects WHERE bargain_search_id=?", (sid,)
    ).fetchone() == (0,)


def test_restore_keeps_exclusion_shared_by_another_rejection(site, db):
    seed_listing(db, "r1", price=100.0)
    seed_listing(db, "r2", price=100.0)
    sid = seed_search(db, listing_ids={"r1": "not_match", "r2": "not_match"},
                     exclusions=[])
    db.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, 'r1', 'shared reason')",
        (sid,),
    )
    db.execute(
        "INSERT INTO rejects (bargain_search_id, listing_id, reason) VALUES (?, 'r2', 'shared reason')",
        (sid,),
    )
    db.commit()

    status, body, _ = call("DELETE",
                          f"{site}/api/v1/searches/{sid}/rejections/r1")
    assert status == 200
    assert body["exclusions"] == ["shared reason"]


def test_restore_rejection_missing_search(site, db):
    seed_listing(db, "r1", price=100.0)
    status, body, _ = call("DELETE", f"{site}/api/v1/searches/999/rejections/r1")
    assert status == 404
    assert body["error"]["code"] == "search_not_found"


def test_restore_rejection_not_found(site, db):
    seed_listing(db, "r1", price=100.0)
    sid = seed_search(db)
    status, body, _ = call("DELETE",
                          f"{site}/api/v1/searches/{sid}/rejections/r1")
    assert status == 404
    assert body["error"]["code"] == "rejection_not_found"


# --- PATCH /enrichments/{listing_id} (Correction) ------------------------------


def test_correction_sets_everything_and_mints(site, db):
    seed_listing(db, "x1", price=100.0)
    body = {
        "product_identity": "Dell Optiplex 7080 i5-10500/16GB",
        "condition": "complete",
        "bundle": [{"description": "mouse", "confidence": "high"}],
    }
    status, out, _ = call("PATCH", f"{site}/api/v1/enrichments/x1", body)
    assert status == 200
    assert set(out) == CORRECTION_KEYS
    assert out["corrected"] is True
    assert out["status"] == "enriched"
    assert out["product"]["action"] == "mint"
    assert out["product"]["description"] == body["product_identity"]
    minted = db.execute(
        "SELECT id FROM product_identities WHERE description=?",
        (body["product_identity"],),
    ).fetchone()
    assert minted is not None
    assert out["product"]["matched_id"] == minted[0]
    assert db.execute(
        "SELECT product_identity_id FROM listings WHERE id='x1'"
    ).fetchone() == (minted[0],)
    row = db.execute(
        "SELECT corrected, condition, bundle FROM enrichments WHERE listing_id='x1'"
    ).fetchone()
    assert row[0] == 1
    assert row[1] == "complete"
    assert json.loads(row[2]) == body["bundle"]


def test_correction_matches_existing_identity(site, db):
    iid = seed_identity(db, "Dell Optiplex 7080 i5-10500/16GB")
    seed_listing(db, "x2", price=100.0)
    status, out, _ = call("PATCH", f"{site}/api/v1/enrichments/x2",
                         {"product_identity": "Dell Optiplex 7080 i5-10500/16GB"})
    assert status == 200
    assert out["product"]["action"] == "match"
    assert out["product"]["matched_id"] == iid
    # No duplicate identity was minted.
    assert db.execute(
        "SELECT COUNT(*) FROM product_identities"
    ).fetchone() == (1,)


def test_correction_partial_condition_only(site, db):
    iid = seed_identity(db)
    seed_listing(db, "x3", price=50.0, identity_id=iid)
    seed_enrichment(db, "x3", matched_id=iid, condition="complete")
    status, out, _ = call("PATCH", f"{site}/api/v1/enrichments/x3",
                         {"condition": "cosmetic damage"})
    assert status == 200
    assert out["condition"] == "cosmetic damage"
    # Untouched fields keep their seeded values (raw JSON arrays on the wire).
    assert out["bundle"] == []


def test_correction_survives_re_enrichment(site, db, monkeypatch):
    """A corrected record is frozen: a later Enrichment pass skips it."""
    from src import fanout
    from src.marketplace import ListingDetail

    iid = seed_identity(db, "The corrected truth")
    seed_listing(db, "x4", price=50.0, identity_id=iid)
    call("PATCH", f"{site}/api/v1/enrichments/x4",
         {"product_identity": "The corrected truth",
          "condition": "refurbished",
          "bundle": [{"description": "mouse", "confidence": "high"}]})
    before = db.execute(
        "SELECT product, condition, bundle, corrected, status "
        "FROM enrichments WHERE listing_id='x4'"
    ).fetchone()

    calls = {"n": 0}

    def fake_enrich(*a, **k):
        calls["n"] += 1
        raise AssertionError("model must not run on a corrected listing")

    class FakeMP:
        def fetch_detail(self, listing):
            return ListingDetail(description="model bait", shipping_cost=5.0)

    monkeypatch.setattr(fanout.router, "enrich", fake_enrich)
    ok = fanout._enrich_one(db, {"offerup": FakeMP()}, "x4")
    assert ok is True
    assert calls["n"] == 0
    after = db.execute(
        "SELECT product, condition, bundle, corrected, status "
        "FROM enrichments WHERE listing_id='x4'"
    ).fetchone()
    assert after == before


def test_correction_listing_missing(site):
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/nope",
                          {"condition": "complete"})
    assert status == 404
    assert body["error"]["code"] == "listing_not_found"


def test_correction_empty_body_400(site, db):
    seed_listing(db, "x5")
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/x5", {})
    assert status == 400
    assert body["error"]["code"] == "invalid_correction"


def test_correction_malformed_400(site):
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/x5", raw=b"nope")
    assert status == 400
    assert body["error"]["code"] == "malformed_request"


def test_correction_bad_condition_422(site, db):
    seed_listing(db, "x6")
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/x6",
                          {"condition": "barely alive"})
    assert status == 422
    assert body["error"]["code"] == "invalid_correction"


def test_correction_bad_bundle_422(site, db):
    seed_listing(db, "x7")
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/x7",
                          {"bundle": [{"confidence": "high"}]})
    assert status == 422
    assert body["error"]["code"] == "invalid_correction"
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/x7",
                          {"bundle": "not a list"})
    assert status == 422
    assert body["error"]["code"] == "invalid_correction"


def test_correction_blank_identity_422(site, db):
    seed_listing(db, "x8")
    status, body, _ = call("PATCH", f"{site}/api/v1/enrichments/x8",
                          {"product_identity": "   "})
    assert status == 422
    assert body["error"]["code"] == "invalid_correction"


# --- max_price on results now filters the effective price ----------------------


def test_results_max_price_uses_effective_price(site, db):
    """Ask 100 + shipping 10 - flip 30 = effective 80: a max_price of 85
    keeps it although the ask alone (100) would have excluded it."""
    warranty = seed_identity(db, "extended warranty")
    main = seed_identity(db, "Dell Optiplex 7080")
    seed_obs(db, "w_obs", warranty, "complete", [30.0] * 5)
    seed_listing(db, "a", price=100.0, shipping=10.0, identity_id=main)
    seed_enrichment(db, "a", description="Dell Optiplex 7080", matched_id=main,
                   condition="complete",
                   bundle=[{"description": "extended warranty",
                           "confidence": "high"}])
    seed_search(db, listing_ids={"a": "match"})

    _, body, _ = call("GET",
                     f"{site}/api/v1/searches/1/results?max_price=85")
    assert [i["listing_id"] for i in body["items"]] == ["a"]
    card = body["items"][0]
    assert card["effective_price"] == 80.0

    _, body, _ = call("GET",
                     f"{site}/api/v1/searches/1/results?max_price=75")
    assert body["items"] == []


def test_result_card_carries_computed_fields(site, db):
    pid = seed_identity(db, "HP Z440 workstation")
    seed_obs(db, "obs1", pid, "complete", [150.0, 200.0, 220.0, 180.0, 200.0])
    seed_listing(db, "a", price=120.0, shipping=10.0, identity_id=pid)
    seed_enrichment(db, "a", condition="complete")
    seed_search(db, listing_ids={"a": "match"})
    _, body, _ = call("GET", f"{site}/api/v1/searches/1/results")
    card = body["items"][0]
    assert card["shipping"] == 10.0
    assert card["effective_price"] == 130.0
    assert card["fair_price"] == 200.0
    assert card["margin_pct"] == 35.0
    assert card["n_observations"] == 5


def test_result_card_cold_start_computed_fields_are_null(site, db):
    seed_listing(db, "a", price=120.0)
    seed_search(db, listing_ids={"a": "match"})
    _, body, _ = call("GET", f"{site}/api/v1/searches/1/results")
    card = body["items"][0]
    assert card["shipping"] is None
    assert card["effective_price"] == 120.0
    assert card["fair_price"] is None
    assert card["margin_pct"] is None
    assert card["n_observations"] is None
