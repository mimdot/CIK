#!/usr/bin/env python3
"""What EURAXESS is actually ASKED, not just what it answers.

The failure this pins is invisible to a status-code or listing-count check.
The crawler reads a bounded number of pages, so a country filter applied
AFTERWARDS cannot reach a post the board would have shown on page 9 — the
result is not "slower", it is missing, at any page depth the crawler uses.

Measured against the live portal on 2026-08-15, astronomy profile, Germany:

    physics sweep, no country facet   1 kept   (30 fetched, 5 German-tagged)
    physics sweep, country facet      6 kept   (5 of them previously unreachable)

Facet semantics, also measured that day: values of the SAME key OR, values of
DIFFERENT keys AND. So adding job_country narrows an existing sweep and never
widens it, and several countries can share one query.
"""

from __future__ import annotations

import argparse

import pytest
from bs4 import BeautifulSoup

from core.config import build_config
from core.deps import _HTML_PARSER
from sources.euraxess import UNSCOPED_PAGES, source_euraxess


def _cfg(field="astronomy", countries=("Germany",)):
    return build_config(argparse.Namespace(
        country=list(countries) if countries else None,
        field=field, subfields=[], include_slow_sources=False,
        types=None, no_config=True))


_CARD = ("<article class='ecl-content-item'>"
         "<h3 class='ecl-content-block__title'>"
         "<a href='/jobs/{n}'>PhD position {n}</a></h3>"
         "</article>")


class _FakeHttp:
    """Records every query, and always serves a full page so pagination runs
    to each query's own limit (the crawler stops early only on a short page)."""

    def __init__(self, cards=10):
        self.calls: list[list[tuple[str, str]]] = []
        self._html = "".join(_CARD.format(n=i) for i in range(cards))

    def get_soup(self, url, params=None, **kw):
        self.calls.append(list(params or []))
        return BeautifulSoup(self._html, _HTML_PARSER)

    def facet_sets(self) -> list[set[str]]:
        return [{v for k, v in call if k.startswith("f[")}
                for call in self.calls]


def test_country_scoped_queries_are_issued():
    """Every facet sweep gets a country-scoped twin carrying job_country."""
    http = _FakeHttp()
    source_euraxess(_cfg(countries=["Germany"]), http)

    scoped = [f for f in http.facet_sets() if "job_country:794" in f]
    assert scoped, "no query asked EURAXESS to filter by country"
    # Narrowing, not replacing: each scoped query keeps its research field.
    for facets in scoped:
        assert any(f.startswith("job_research_field:") or
                   f.startswith("positions:") for f in facets)


def test_the_unscoped_sweep_survives_so_untagged_posts_are_not_lost():
    """A listing the portal never tagged with a country still has to be seen —
    the region filter keeps those under keep_ambiguous."""
    http = _FakeHttp()
    source_euraxess(_cfg(countries=["Germany"]), http)

    unscoped = [f for f in http.facet_sets()
                if not any(x.startswith("job_country:") for x in f)]
    assert unscoped, "the unscoped sweep was dropped entirely"


def test_the_unscoped_sweep_is_shallower_once_a_scoped_one_covers_it():
    """Its remaining job is catching untagged posts, which page 1-2 does."""
    http = _FakeHttp()
    source_euraxess(_cfg(countries=["Germany"]), http)

    pages_by_shape: dict[frozenset, int] = {}
    for call in http.calls:
        shape = frozenset(v for k, v in call if k.startswith("f["))
        pages_by_shape[shape] = pages_by_shape.get(shape, 0) + 1

    for shape, pages in pages_by_shape.items():
        if not any(f.startswith("job_country:") for f in shape):
            assert pages <= UNSCOPED_PAGES, (
                f"unscoped sweep {sorted(shape)} paged {pages} times")


def test_several_countries_share_one_query():
    http = _FakeHttp()
    source_euraxess(_cfg(countries=["Germany", "France"]), http)
    assert any({"job_country:794", "job_country:793"} <= f
               for f in http.facet_sets())


@pytest.mark.parametrize("countries", [None, ["Atlantis"]])
def test_no_country_facet_when_it_cannot_be_resolved(countries):
    """No geo filter, or a country the board does not know: unchanged behaviour
    rather than a search silently scoped to fewer countries."""
    http = _FakeHttp()
    source_euraxess(_cfg(countries=countries), http)
    assert http.calls, "the crawl must still run"
    for facets in http.facet_sets():
        assert not any(f.startswith("job_country:") for f in facets)
