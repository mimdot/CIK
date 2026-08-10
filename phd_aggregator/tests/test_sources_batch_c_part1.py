#!/usr/bin/env python3
"""Unit tests for the Batch C sources (migration Step 5, part 1: findaphd,
academictransfer, aas, linkedin, uni_departments, stubs).

Each source stays self-contained: it takes (cfg, http) and returns raw records
via make_record. We build tiny stub http objects feeding the same markup the
live runs exercise, then assert the normalized records come out. No network.
"""
import pytest

from sources.aas import source_aas
from sources.academictransfer import _academictransfer_ssr_fallback, source_academictransfer
from sources.findaphd import source_findaphd
from sources.linkedin import _linkedin_card, source_linkedin
from sources.stubs import source_astrobetter, source_iau


class _Soup:
    """Minimal BeautifulSoup-ish double with find/find_all/get_text/select."""

    def __init__(self, text="", is_none=False, **attrs):
        self._text = text
        self.attrs = attrs
        self.is_none = is_none

    def get_text(self, sep="", strip=False):
        return self._text.strip() if strip else self._text

    def find(self, name=None, href=None, class_=None, **kw):
        return None

    def find_all(self, name=None, class_=None, href=None, **kw):
        return []

    def find_parent(self, name=None, **kw):
        return None

    def find_previous(self, *a, **k):
        return None

    def select_one(self, *a, **k):
        return None

    def select(self, *a, **k):
        return []


def _mk_cfg():
    class Cfg:
        search_terms = ["astrophysics"]
        countries = []
        geo_filter_active = False
    return Cfg()


# --- linkedin ---------------------------------------------------------------
class _Txt:
    """dict-like element double for get_text()/get()/subscript."""
    def __init__(self, t, href=None, datetime=None):
        self._t = t
        self._m = {"href": href or "https://www.linkedin.com/jobs/view/1?trk=x",
                   "datetime": datetime or "2026-07-01"}
    def get_text(self, sep=" ", strip=True):
        return self._t
    def get(self, k, default=None):
        return self._m.get(k, default)
    def __getitem__(self, k):
        return self._m[k]


def test_linkedin_card_rejects_contractor_gig():
    # a gig-y title must be rejected at the card level
    assert _linkedin_card(_Card("[PhD peer review need $90/hr remote]")) is None


class _Card:
    """Very small fake exposing select_one used by _linkedin_card."""
    def __init__(self, label):
        self.label = label

    def select_one(self, sel, **kw):
        if sel == "a.base-card__full-link[href]" or sel == "a[href]":
            return _Txt("", href="https://www.linkedin.com/jobs/view/1?trk=x")
        if sel == "h3.base-search-card__title" or sel == "h3":
            return _Txt(self.label)
        if sel == "h4.base-search-card__subtitle":
            return _Txt("Some Lab")
        if sel == "span.job-search-card__location":
            return _Txt("Bonn, NRW, Germany")
        if sel == "time[datetime]":
            return _Txt("", datetime="2026-07-01")
        return None


def test_linkedin_card_parses_fields():
    rec = _linkedin_card(_Card("PhD researcher in radio astronomy"))
    assert rec is not None
    assert rec["title"] == "PhD researcher in radio astronomy"
    assert rec["institution"] == "Some Lab"
    assert rec["country"] == "Germany"
    assert rec["posted_date"] == "2026-07-01"
    assert rec["source"] == "linkedin"
    assert rec["url"] == "https://www.linkedin.com/jobs/view/1"


# --- aas -----------------------------------------------------------------

def test_aas_uses_feed_when_available():
    class Http:
        def __init__(self):
            self.feed = _FakeFeed([{"title": "PhD studentship",
                                    "summary": "radio astronomy",
                                    "link": "https://jobregister.aas.org/jobs/1"}])
        def get_feed(self, url, **kw):
            return self.feed
        def get_rendered(self, url, **kw):
            return None

    recs = source_aas(_mk_cfg(), Http())
    assert len(recs) == 1
    assert recs[0]["title"] == "PhD studentship"
    assert recs[0]["source"] == "aas"


class _FakeFeed:
    """dict-like feed with `.entries` and per-entry .get()."""
    def __init__(self, entries):
        self.entries = [_FeedEntry(e) for e in entries]


class _FeedEntry(dict):
    pass


# --- academictransfer SSR fallback ----------------------------------------

def test_academictransfer_ssr_fallback_parses_links():
    html = ("<html><body>"
            "<a href='/en/jobs/361520/phd-position-in-astronomy/'>PhD in astronomy</a>"
            "<a href='/en/jobs/361521/'>Other post</a>"
            "</body></html>")
    from bs4 import BeautifulSoup
    from core.deps import _HTML_PARSER
    soup = BeautifulSoup(html, _HTML_PARSER)

    class _FakeHttp:
        def get_soup(self, url, **kw):
            return soup

    records = _academictransfer_ssr_fallback(_mk_cfg(), _FakeHttp())
    assert len(records) == 2
    assert records[0]["title"] == "PhD in astronomy"
    assert records[0]["url"].startswith("https://www.academictransfer.com")
    assert records[0]["country"] == "Netherlands"
    assert records[0]["source"] == "academictransfer"


# --- aas: no feed -> must not crash, returns [] (browser path untestable) ---
def test_aas_no_feed_returns_empty():
    class Http:
        def get_feed(self, url, **kw):
            return None
        def get_rendered(self, url, **kw):
            return None
    assert source_aas(_mk_cfg(), Http()) == []


# --- stubs ---------------------------------------------------------------

def test_stubs_return_empty_without_fetching():
    assert source_iau(_mk_cfg(), object()) == []
    assert source_astrobetter(_mk_cfg(), object()) == []