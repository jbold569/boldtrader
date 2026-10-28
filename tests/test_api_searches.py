"""Contract tests for the Bargain Search JSON API (ticket #38).

Live ThreadingHTTPServer + urllib over a temp DB, in the style of
tests/test_search_page.py. Covers GET/POST/PATCH/DELETE on
/api/v1/searches: the pagination envelope, the created/updated search
resource, the fan-out kick, invalid_draft 422s, 404/400 error bodies.
Fan-out is faked; the network and the model are never touched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.db import init_db

API = "/api/v1/searches"

VALID_DRAFT = {
    "summary": "HP Z440 workstations under $300",
    "product_identity": "HP Z440",
    "queries": ["hp z440", "z440 workstation"],
    "exclusions": ["no monitor"],
    "target_price": 300.0,
    "location": "Kenmore, WA",
}

RESOURCE_KEYS = {
    "id",
    "summary",
    "product_identity",
    "target_price",
    "location",
    "queries",
    "exclusions",
    "version",
    "status",
    "match_count",
    "created_at",
    "updated_at",
}

LIST_ITEM_KEYS = {"id", "summary", "status", "match_count", "updated_at"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Live server on an ephemeral port with a temp DB; fan-out faked."""
    path = tmp_path / "api.db"
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
def fanout(site, monkeypatch):
    """Records fan_out invocations instead of running them."""
    recorded: list[tuple] = []

    def fake_fan_out(marketplaces, search_id, location=None):
        recorded.append((search_id, location))

    monkeypatch.setattr("src.api.fan_out", fake_fan_out)
    return recorded


def call(method: str, url: str, body=None, raw: bytes | None = None):
    """One HTTP round-trip; returns (status, parsed_json_or_None, headers)."""
    data = raw if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else None
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


def create(site: str, **overrides) -> dict:
    """POST a valid draft and return the created resource."""
    status, resource, _ = call(
        "POST", site + API, {**VALID_DRAFT, **overrides}
    )
    assert status == 201, resource
    return resource


# --- GET /api/v1/searches: pagination envelope -------------------------------


def test_list_envelope_shape(site):
    create(site)
    create(site, summary="second")
    status, body, headers = call("GET", site + API)
    assert status == 200
    assert "application/json" in headers.get("Content-Type", "")
    assert set(body) == {"items", "page", "per_page", "total", "total_pages"}
    assert body["total"] == 2
    assert body["total_pages"] == 1
    assert len(body["items"]) == 2


def test_list_items_carry_only_list_fields(site):
    create(site)
    _, body, _ = call("GET", site + API)
    item = body["items"][0]
    assert set(item) == LIST_ITEM_KEYS
    assert item["summary"] == VALID_DRAFT["summary"]
    assert item["status"] in ("active", "running", "enriching", "complete")
    assert item["match_count"] == 0


def test_list_defaults_are_page_1_per_page_50(site):
    _, body, _ = call("GET", site + API)
    assert body["page"] == 1
    assert body["per_page"] == 50


def test_list_per_page_capped_at_200(site):
    _, body, _ = call("GET", site + API + "?per_page=500")
    assert body["per_page"] == 200


def test_list_respects_paging(site):
    for i in range(3):
        create(site, summary=f"search {i}")
    _, body, _ = call("GET", site + API + "?page=2&per_page=1")
    assert body["page"] == 2
    assert body["per_page"] == 1
    assert body["total_pages"] == 3
    assert len(body["items"]) == 1
    assert body["items"][0]["summary"] == "search 1"


def test_list_bad_page_is_400(site):
    status, body, headers = call("GET", site + API + "?page=abc")
    assert status == 400
    assert "application/json" in headers.get("Content-Type", "")
    assert set(body["error"]) == {"code", "message"}


# --- POST /api/v1/searches: create -------------------------------------------


def test_create_returns_full_resource(site, fanout):
    status, resource, headers = call("POST", site + API, VALID_DRAFT)
    assert status == 201
    assert "application/json" in headers.get("Content-Type", "")
    assert set(resource) == RESOURCE_KEYS
    assert resource["id"] == 1
    assert resource["version"] == 1
    assert resource["status"] == "active"
    assert resource["match_count"] == 0
    assert resource["target_price"] == 300.0
    assert resource["queries"] == VALID_DRAFT["queries"]
    assert resource["created_at"] and resource["updated_at"]


def test_create_persists_and_kicks_fanout(site, fanout):
    resource = create(site)
    row = sqlite3.connect(os.environ["BOLDTRADER_DB"]).execute(
        "SELECT summary, status FROM bargain_searches WHERE id=?", (resource["id"],)
    ).fetchone()
    assert row == ("HP Z440 workstations under $300", "active")
    assert fanout == [(resource["id"], "Kenmore, WA")]


def test_create_missing_required_field_is_422_invalid_draft(site, fanout):
    body = {k: v for k, v in VALID_DRAFT.items() if k != "queries"}
    status, err, _ = call("POST", site + API, body)
    assert status == 422
    assert err["error"]["code"] == "invalid_draft"
    assert err["error"]["message"]
    assert fanout == []


def test_create_query_duplicating_exclusion_is_422_invalid_draft(site, fanout):
    draft = dict(
        VALID_DRAFT,
        queries=["hp z440", "no monitor"],
        exclusions=["no monitor"],
    )
    status, err, _ = call("POST", site + API, draft)
    assert status == 422
    assert err["error"]["code"] == "invalid_draft"
    assert "no monitor" in err["error"]["message"]
    assert fanout == []


def test_create_negative_target_price_is_422(site, fanout):
    status, err, _ = call("POST", site + API, dict(VALID_DRAFT, target_price=-5))
    assert status == 422
    assert err["error"]["code"] == "invalid_draft"


# --- PATCH /api/v1/searches/{id} ---------------------------------------------


def test_patch_partial_update_bumps_version_and_kicks_fanout(site, fanout):
    created = create(site)
    status, patched, _ = call(
        "PATCH", f"{site}{API}/{created['id']}", {"target_price": 150.0}
    )
    assert status == 200
    assert patched["version"] == 2
    assert patched["target_price"] == 150.0
    assert patched["summary"] == VALID_DRAFT["summary"]
    assert patched["id"] == created["id"]
    assert fanout[-1] == (created["id"], "Kenmore, WA")


def test_patch_validation_failure_is_422_and_bumps_nothing(site, fanout):
    created = create(site)
    status, err, _ = call("PATCH", f"{site}{API}/{created['id']}", {"queries": []})
    assert status == 422
    assert err["error"]["code"] == "invalid_draft"
    status, after, _ = call("GET", f"{site}{API}?page=1&per_page=1")
    assert after["items"][0]["updated_at"] == created["updated_at"]


def test_patch_missing_search_is_404(site, fanout):
    status, err, headers = call("PATCH", f"{site}{API}/999", {"target_price": 5.0})
    assert status == 404
    assert err["error"]["code"] == "search_not_found"
    assert "999" in err["error"]["message"]
    assert fanout == []
    assert "application/json" in headers.get("Content-Type", "")


def test_patch_cross_field_conflict_is_422(site, fanout):
    created = create(site)
    after_create = len(fanout)  # the create's fan-out kick (0 or 1, async)
    status, err, _ = call(
        "PATCH", f"{site}{API}/{created['id']}", {"queries": ["no monitor"]}
    )
    assert status == 422
    assert err["error"]["code"] == "invalid_draft"
    assert len(fanout) <= 1  # the rejected patch kicks nothing new


# --- DELETE /api/v1/searches/{id} --------------------------------------------


def test_delete_returns_204_and_removes_search(site):
    created = create(site)
    status, body, _ = call("DELETE", f"{site}{API}/{created['id']}")
    assert status == 204
    assert body is None
    count = sqlite3.connect(os.environ["BOLDTRADER_DB"]).execute(
        "SELECT COUNT(*) FROM bargain_searches"
    ).fetchone()[0]
    assert count == 0


def test_delete_missing_search_is_404(site):
    status, err, _ = call("DELETE", f"{site}{API}/999")
    assert status == 404
    assert err["error"]["code"] == "search_not_found"


# --- Error body shape ---------------------------------------------------------


def test_404_body_is_json_error_not_html(site):
    status, err, headers = call("GET", site + "/api/v1/nonexistent")
    assert status == 404
    assert "application/json" in headers.get("Content-Type", "")
    assert set(err["error"]) == {"code", "message"}
    assert "<html" not in json.dumps(err).lower()


def test_malformed_json_body_is_400(site, fanout):
    status, err, headers = call("POST", site + API, raw=b"{not json")
    assert status == 400
    assert "application/json" in headers.get("Content-Type", "")
    assert set(err["error"]) == {"code", "message"}
    assert fanout == []


# --- GET /api/v1/searches/{id}: single resource (ticket #45) -----------------


def test_get_one_returns_full_resource(site):
    created = create(site, summary="single get")
    status, resource, headers = call("GET", f"{site}{API}/{created['id']}")
    assert status == 200
    assert "application/json" in headers.get("Content-Type", "")
    assert set(resource) == RESOURCE_KEYS
    assert resource["id"] == created["id"]
    assert resource["summary"] == "single get"


def test_get_one_reflects_patch(site, fanout):
    created = create(site)
    call(
        "PATCH",
        f"{site}{API}/{created['id']}",
        {"target_price": 111.0, "summary": "renamed"},
    )
    _, resource, _ = call("GET", f"{site}{API}/{created['id']}")
    assert resource["summary"] == "renamed"
    assert resource["target_price"] == 111.0
    assert resource["version"] > created["version"]


def test_get_one_missing_search_is_404(site):
    status, err, headers = call("GET", f"{site}{API}/999")
    assert status == 404
    assert err["error"]["code"] == "search_not_found"
    assert "999" in err["error"]["message"]
    assert "application/json" in headers.get("Content-Type", "")


def test_get_one_non_numeric_id_is_404(site):
    status, err, _ = call("GET", f"{site}{API}/abc")
    assert status == 404
    assert err["error"]["code"] == "search_not_found"
