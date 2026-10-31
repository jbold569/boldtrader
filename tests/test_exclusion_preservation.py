"""Exclusion preservation through every description rewrite (ticket #61).

The Exclusions block at the end of a Product Identity's description is
user-asserted fact (it arrives via rejections). Any automatic rewrite —
first synthesis, retune, the explicit POST retune endpoint — must keep
every exclusion line. The prompt asks the model to preserve them; the
post-write validation is the guarantee: any line missing from the model
output is force re-appended before persisting.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import router
from src.db import init_db
from src import identity as ident


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "excl.db"
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
    path = tmp_path / "excl.db"
    init_db(path).close()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return exc.code, parsed


def seed_listing(conn, lid, title="a listing"):
    raw = {"id": lid, "title": title, "price": 100.0, "marketplace": "offerup"}
    conn.execute("INSERT INTO listings (id, raw) VALUES (?, ?)",
                (lid, json.dumps(raw)))
    conn.commit()


def seed_search(conn, iid):
    cur = conn.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status, "
        "listing_ids, product_identity_id) VALUES ('s', 'p', 'complete', '{\"m\": \"match\"}', ?)",
        (iid,),
    )
    conn.commit()
    return cur.lastrowid


# --- helpers ----------------------------------------------------------------


def test_split_exclusions_without_block():
    body, lines = ident.split_exclusions("Just a plain description.")
    assert body == "Just a plain description."
    assert lines == []


def test_split_exclusions_with_block():
    body, lines = ident.split_exclusions(
        "The product.\n\nExclusions:\nno monitors\nno keyboards"
    )
    assert body == "The product."
    assert lines == ["no monitors", "no keyboards"]


def test_render_roundtrip():
    text = ident.render_exclusions("The product.", ["no monitors"])
    assert text == "The product.\n\nExclusions:\nno monitors"
    body, lines = ident.split_exclusions(text)
    assert body == "The product."
    assert lines == ["no monitors"]


def test_render_without_lines_is_just_body():
    assert ident.render_exclusions("Only body.", []) == "Only body."


# --- synthesis path ----------------------------------------------------------


def test_synthesis_missing_exclusion_is_reappended(db, monkeypatch):
    """The fake model drops the exclusion line from its rewrite; the
    stored description still carries it."""
    cur = db.execute(
        "INSERT INTO product_identities (description) VALUES (?)",
        ("old wording\n\nExclusions:\nno monitors",),
    )
    db.commit()
    iid = cur.lastrowid
    seed_listing(db, "m")
    sid = seed_search(db, iid)
    monkeypatch.setattr(
        router, "synthesize_description",
        lambda evidence, model=None: "New rewritten wording.",
    )
    ident.update_identity_from_search(db, sid)
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert desc == "New rewritten wording.\n\nExclusions:\nno monitors"


def test_synthesis_dropped_exclusion_survives_second_rewrite(db, monkeypatch):
    """After the first rewrite re-appends the line, a second rewrite that
    drops it again must still end up with exactly one copy."""
    cur = db.execute(
        "INSERT INTO product_identities (description) VALUES (?)",
        ("v1\n\nExclusions:\nno monitors",),
    )
    db.commit()
    iid = cur.lastrowid
    seed_listing(db, "m")
    sid = seed_search(db, iid)
    monkeypatch.setattr(
        router, "synthesize_description",
        lambda evidence, model=None: "v2 prose.",
    )
    ident.update_identity_from_search(db, sid)
    ident.update_identity_from_search(db, sid)
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert desc == "v2 prose.\n\nExclusions:\nno monitors"
    assert desc.count("no monitors") == 1


# --- explicit retune (HTTP) path ----------------------------------------------


def test_retune_reappends_missing_exclusion(site, db, monkeypatch):
    cur = db.execute(
        "INSERT INTO product_identities (description, synthesized_at) VALUES (?, ?)",
        ("old description\n\nExclusions:\nnever accept monitors",
         "2026-10-01 00:00:00"),
    )
    db.commit()
    iid = cur.lastrowid
    seed_listing(db, "m")
    db.execute(
        "INSERT INTO bargain_searches (summary, product_identity, status, "
        "listing_ids, product_identity_id) VALUES ('s', 'p', 'complete', '{\"m\": \"match\"}', ?)",
        (iid,),
    )
    db.commit()
    monkeypatch.setattr(
        router, "synthesize_description",
        lambda evidence, model=None: "Retuned wording.",
    )
    status, body = call("POST", f"{site}/api/v1/product-identities/{iid}/retune")
    assert status == 200
    desc = db.execute(
        "SELECT description FROM product_identities WHERE id=?", (iid,)
    ).fetchone()[0]
    assert desc == "Retuned wording.\n\nExclusions:\nnever accept monitors"
