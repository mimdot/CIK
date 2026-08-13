"""tests.test_http_cache — persistent conditional-GET cache (M2).

The cache is disabled under CIK_TESTING, so these tests inject an HttpCache
directly into an Http instance to exercise the revalidation logic offline (no
network, no proxy).
"""

from __future__ import annotations

import argparse

import requests

from core.config import build_config
from core.http import Http
from core.http_cache import (HttpCache, apply_validators, cache_key,
                             response_from_cache)


# --- the store ---------------------------------------------------------------
def test_store_and_get_entry(tmp_path):
    c = HttpCache(str(tmp_path / "c.sqlite"))
    c.store("http://x/a", '"e1"', "Wed, 01 Jan 2026 00:00:00 GMT",
            b"hello", "utf-8")
    e = c.get_entry("http://x/a")
    assert e["etag"] == '"e1"'
    assert e["last_modified"].startswith("Wed")
    assert e["body"] == b"hello"
    assert c.get_entry("http://x/missing") is None
    c.close()


def test_cache_key_folds_params():
    assert cache_key("http://x/a") == "http://x/a"
    k = cache_key("http://x/a", {"b": "2", "a": "1"})
    assert "a=1" in k and "b=2" in k


def test_response_from_cache_decodes_body():
    r = response_from_cache("http://x/a", {"body": "café".encode("utf-8"),
                                           "encoding": "utf-8", "etag": '"e"'})
    assert r.status_code == 200
    assert r.text == "café"
    assert r.headers["X-Cache"] == "HIT"


def test_apply_validators():
    h: dict = {}
    apply_validators(h, {"etag": '"e"', "last_modified": "yesterday"})
    assert h["If-None-Match"] == '"e"'
    assert h["If-Modified-Since"] == "yesterday"


# --- Http integration --------------------------------------------------------
def _http_with_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("core.http._guard_url", lambda u: True)
    cfg = build_config(argparse.Namespace())
    cfg.delay = 0.0
    http = Http(cfg, detect=False)
    http.robots.can_fetch = lambda u: True
    http.robots.crawl_delay = lambda u: 0.0
    http._cache = HttpCache(str(tmp_path / "c.sqlite"))  # bypass the env gate
    return http, cfg


def _resp(status, headers=None, body=b"<html>ok</html>"):
    r = requests.Response()
    r.status_code = status
    r._content = body
    r.encoding = "utf-8"
    for k, v in (headers or {}).items():
        r.headers[k] = v
    return r


def test_get_stores_then_revalidates_with_304(tmp_path, monkeypatch):
    http, cfg = _http_with_cache(tmp_path, monkeypatch)
    seen_headers: list = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen_headers.append(headers or {})
        if len(seen_headers) == 1:
            return _resp(200, {"ETag": '"v1"'}, b"<html>first</html>")
        return _resp(304, {})

    http.session.get = fake_get

    r1 = http.get("http://example.test/list")
    assert r1.text == "<html>first</html>"          # fresh 200, now cached

    r2 = http.get("http://example.test/list")
    assert seen_headers[1].get("If-None-Match") == '"v1"'   # revalidated
    assert r2.status_code == 200
    assert r2.text == "<html>first</html>"           # served from cache
    assert r2.headers.get("X-Cache") == "HIT"


def test_force_refresh_skips_conditional_headers(tmp_path, monkeypatch):
    http, cfg = _http_with_cache(tmp_path, monkeypatch)
    http._cache.store("http://example.test/list", '"v1"', None,
                      b"<html>old</html>", "utf-8")
    cfg.force_refresh = True
    seen_headers: list = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen_headers.append(headers or {})
        return _resp(200, {"ETag": '"v2"'}, b"<html>fresh</html>")

    http.session.get = fake_get

    r = http.get("http://example.test/list")
    assert "If-None-Match" not in (seen_headers[0] or {})   # bypassed
    assert r.text == "<html>fresh</html>"                    # re-fetched
    # ...but the cache is still refreshed for next time.
    assert http._cache.get_entry("http://example.test/list")["etag"] == '"v2"'
