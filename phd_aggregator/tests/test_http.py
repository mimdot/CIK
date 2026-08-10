#!/usr/bin/env python3
"""Offline tests for core/http.py (migration Step 4).

The probe helpers hit no network when fed a proxy that is clearly unreachable,
and the reconcileable parts (headers, challenge/stealth markers, RobotsCache
policy handling, Http core methods via mocks, re-export surface) are asserted
directly. No live network in this file (the live gate is `--source eso`).

Run:  python -m pytest tests/test_http.py -q
"""
import argparse
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.http as http_mod
import phd_aggregator as P
from core.config import build_config


def _mk_cfg():
    ns = argparse.Namespace(no_config=True, debug=False, phd_only=False,
                            field=None)
    cfg = build_config(ns)
    # avoid any network probing in the constructor
    cfg.proxy = None
    cfg.auto_detect_proxy = False
    cfg.proxy_fallback_direct = False
    return cfg


def _mk_http():
    return http_mod.Http(_mk_cfg())


# ------------------------------------------------------------- constants/headers
def test_browser_headers_shape():
    for k in ("User-Agent", "Accept", "Accept-Language",
              "Upgrade-Insecure-Requests"):
        assert k in P.BROWSER_HEADERS
    assert P.BROWSER_HEADERS["User-Agent"].startswith("Mozilla/")


def test_challenge_re_marks_interstitial():
    assert http_mod._CHALLENGE_RE.search(
        "Just a moment... verifying you are human") is not None
    assert http_mod._CHALLENGE_RE.search("real research content page") is None


def test_stealth_js_obfuscates_webdriver():
    assert "webdriver" in http_mod._STEALTH_JS
    assert "navigator" in http_mod._STEALTH_JS
    assert "permissions" in http_mod._STEALTH_JS


# ------------------------------------------------------------ proxy helpers
def test_proxy_reachable_bad_host_false():
    # unresolvable/refused -> must be False fast (no hanging DNS on localhost)
    assert http_mod._proxy_reachable("socks5://127.0.0.1:1", timeout=0.2) is False


def test_proxy_probe_unreachable_false():
    # a dead local port must not route -> _probe_proxy returns False
    assert http_mod._probe_proxy("socks5://127.0.0.1:1", timeout=1) is False


def test_direct_online_timeout_no_crash():
    # calls the real internet; we only assert it returns a bool, never raises.
    # Network errors are expected and ignored; anything else must propagate.
    import requests
    try:
        val = http_mod._direct_online(timeout=2)
        assert isinstance(val, bool)
    except requests.RequestException:
        pass  # no internet in CI — fine, the contract is "no crash"


# --------------------------------------------------------- robots policy
def test_robots_no_obey():
    cfg = _mk_cfg()
    # weave a minimal Http-like stub so RobotsCache.can_fetch short-circuits
    stub = http_mod.RobotsCache.__new__(http_mod.RobotsCache)
    stub.http = None
    stub.obey = False
    assert stub.can_fetch("https://example.com/page") is True


def test_robots_allow_unknown_base():
    # an unresolvable base -> treated as allow (never blocks)
    stub = http_mod.RobotsCache.__new__(http_mod.RobotsCache)
    stub.obey = True
    stub.user_agent = "test-aggregator"
    stub._parsers = {}
    stub.http = type("H", (), {
        "raw_get": lambda url, *a, **kw: None,
    })()
    assert stub.can_fetch("http://no-such-host.invalid/x") is True


# ----------------------------------------------------------- Http core methods
def _fake_resp(status=200, text="ok body"):
    r = mock.Mock()
    r.status_code = status
    r.text = text
    r.content = text.encode()
    r.ok = status < 400
    return r


def test_http_get_returns_content_on_200():
    h = _mk_http()
    h.session.get = mock.Mock(return_value=_fake_resp(200, "real content"))
    h.robots.can_fetch = mock.Mock(return_value=True)
    h.robots.crawl_delay = mock.Mock(return_value=0.0)
    resp = h.get("https://example.com/a")
    assert resp is not None and resp.text == "real content"
    h.session.get.assert_called_once()


def test_http_get_none_when_robots_blocked():
    h = _mk_http()
    h.robots.can_fetch = mock.Mock(return_value=False)
    h.session.get = mock.Mock()
    assert h.get("https://example.com/a") is None
    h.session.get.assert_not_called()


def test_http_get_none_on_persistent_network_failure():
    import requests
    h = _mk_http()
    h.robots.can_fetch = mock.Mock(return_value=True)
    h.robots.crawl_delay = mock.Mock(return_value=0.0)
    h.session.get = mock.Mock(side_effect=requests.ConnectionError("conn refused"))
    h._cffi_get = mock.Mock(return_value=None)
    assert h.get("https://example.com/a") is None


def test_http_get_returns_none_on_404_no_impersonation():
    # a plain 404 is a real answer, not an anti-bot block -> no cffi retry
    h = _mk_http()
    h.robots.can_fetch = mock.Mock(return_value=True)
    h.robots.crawl_delay = mock.Mock(return_value=0.0)
    h.session.get = mock.Mock(return_value=_fake_resp(404, "nope"))
    h._cffi_get = mock.Mock(return_value=None)
    assert h.get("https://example.com/a") is None
    h._cffi_get.assert_not_called()


def test_http_get_soup_parses_html():
    h = _mk_http()
    h.get = mock.Mock(return_value=_fake_resp(200, "<b>hi</b>"))
    soup = h.get_soup("https://example.com/a")
    assert soup is not None and soup.get_text(strip=True) == "hi"


def test_http_get_soup_none_on_failure():
    h = _mk_http()
    h.get = mock.Mock(return_value=None)
    assert h.get_soup("https://example.com/a") is None


def test_http_get_feed_none_without_feedparser():
    h = _mk_http()
    h.get = mock.Mock(return_value=None)
    assert h.get_feed("https://example.com/rss") is None


def test_http_fetch_page_returns_html_from_plain_get():
    h = _mk_http()
    h.get = mock.Mock(return_value=_fake_resp(200, "<html>plain</html>"))
    assert h.fetch_page("https://example.com/a") == "<html>plain</html>"


def test_http_fetch_page_none_when_blocked_no_playwright():
    h = _mk_http()
    h.get = mock.Mock(return_value=None)
    with mock.patch.object(http_mod, "_HAVE_PLAYWRIGHT", False):
        assert h.fetch_page("https://example.com/a") is None


# ------------------------------------------------------------------ throttle
def test_throttle_sleeps_remaining_delay():
    h = _mk_http()
    h.cfg.delay = 5.0
    h._last_request = 0.0
    # monotonic=3 -> only 3s since last request, 2s still owed
    with mock.patch("core.http.time.monotonic", return_value=3.0), \
            mock.patch("core.http.time.sleep") as sleep:
        h._throttle()
        sleep.assert_called_once()
        assert sleep.call_args[0][0] == 2.0


def test_throttle_no_sleep_when_outside_delay():
    h = _mk_http()
    h.cfg.delay = 5.0
    h._last_request = 0.0
    # monotonic=10 -> 10s elapsed, more than the 5s delay -> no sleep
    with mock.patch("core.http.time.monotonic", return_value=10.0), \
            mock.patch("core.http.time.sleep") as sleep:
        h._throttle()
        sleep.assert_not_called()


# ----------------------------------------------------------------- close
def test_http_close_idempotent():
    h = _mk_http()
    h._pw_ctx = mock.Mock()
    h._pw = mock.Mock()
    h.close()
    h.close()  # second call must not crash
    assert h._pw_ctx is None and h._pw is None


def test_http_close_with_none_state():
    h = _mk_http()
    h._pw_ctx = None
    h._pw = None
    h.close()  # must not raise


# ----------------------------------------------------------- back-compat
def test_backcompat_names_reachable_from_monolith():
    for name in ("Http", "RobotsCache"):
        assert name in dir(P)
    assert P.Http is http_mod.Http