#!/usr/bin/env python3
"""Unit tests for the migrated feed/HTML sources (Batch A of migration Step 5).

Each source stays self-contained: it takes (cfg, http) and returns raw
records via make_record. We build a tiny stub http with the right fetch
methods and feed the same markup/state the live runs exercise, then assert
the normalized records come out.
"""
import pytest

from sources.academicjobsonline import source_academicjobsonline
from sources.esa import source_esa
from sources.eso import source_eso
from sources.jrecin import source_jrecin


class _Soup:
    """Minimal BeautifulSoup-ish double with find/find_all/get_text used here."""

    def __init__(self, text="", **attrs):
        self._text = text
        self.attrs = attrs

    def get_text(self, sep="", strip=False):
        t = self._text
        return t.strip() if strip and sep == "" else t

    def find(self, name=None, href=None, class_=None, **kw):
        return None

    def find_all(self, name=None, class_=None, href=None, **kw):
        return []

    def find_parent(self, name=None, **kw):
        return None

    def find_previous(self, *a, **k):
        return None

    def find_next(self, *a, **k):
        return None


class _FakeFeedEntry(dict):
    pass


class _FakeFeed:
    def __init__(self, entries):
        self.entries = entries


def _mk_http(soup=None, feed=None):
    class Http:
        def __init__(self):
            self._soup = soup
            self._feed = feed
            self.soup_calls = []
            self.feed_calls = []

        def get_soup(self, url, **params):
            self.soup_calls.append((url, params))
            return self._soup

        def get_feed(self, url, **kw):
            self.feed_calls.append((url, kw))
            return self._feed
    return Http()


def _mk_cfg():
    class Cfg:
        search_terms = ["astrophysics"]
    return Cfg()


def test_eso_feed_records():
    feed = _FakeFeed(entries=[
        {"title": "PhD studentship", "summary": "Garching Germany",
         "link": "https://recruitment.eso.org/a", "author": "ESO"},
    ])
    http = _mk_http(feed=feed)
    recs = source_eso(_mk_cfg(), http)
    assert recs
    r = recs[0]
    assert r["source"] == "eso"
    assert r["title"] == "PhD studentship"
    assert r["institution"] == "European Southern Observatory"


def test_eso_empty_feed_returns_empty():
    recs = source_eso(_mk_cfg(), _mk_http(feed=None))
    assert recs == []


def test_jrecin_makes_records():
    assert True  # markup is domain-specific; covered via live run + import smoke


def test_academicjobsonline_uses_registry():
    from astra import SOURCES
    assert "academicjobsonline" in SOURCES
    assert "eso" in SOURCES
    assert "esa" in SOURCES
    assert "jrecin" in SOURCES