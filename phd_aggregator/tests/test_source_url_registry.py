#!/usr/bin/env python3
"""The per-source URL registry, and the fixtures that pin each board's selector.

Two failure modes these exist for.

1. WRONG URL. Source URLs were built by pasting the field name into a path, so
   "astrophysics" became https://www.findaphd.com/phds/astrophysics/ — which is
   FindAPhD's own 404 page. The board's slug is the board's vocabulary; it is
   data now, not string arithmetic.

2. RIGHT-LOOKING URL, WRONG RESULT SET. AcademicJobsOnline answers 200 for ANY
   path and serves a generic fallback listing for one it does not know. Five
   slugs that shipped for months (mathematics, statistics, economics,
   engineering, geosciences) were all silently that same page. Status code and
   listing count both looked healthy.

So the registry is asserted against, and the parse selectors are pinned to
saved HTML captured from the live boards.
"""

from __future__ import annotations

import pathlib

import pytest

from sources import registry

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# --- the registry itself -------------------------------------------------------

def test_registry_loads_every_source():
    specs = registry.load_registry(force=True)
    for name in ("findaphd", "aas", "euraxess", "academicjobsonline",
                 "jobs_ac_uk", "nature_careers", "academictransfer"):
        assert name in specs, f"{name} missing from url_registry.yaml"


def test_every_entry_declares_its_verification_status():
    """An entry with no status is a guess nobody can audit."""
    for spec, target in registry.iter_entries():
        assert target.status in {"ok", "unverified", "blocked"}, (
            f"{spec.name}/{target.field} has status {target.status!r}")


def test_facet_sources_build_drupal_facet_urls():
    spec = registry.spec_for("euraxess")
    urls = spec.urls_for("chemistry")
    assert urls == [
        "https://euraxess.ec.europa.eu/jobs/search"
        "?f%5B0%5D=job_research_field%3A47"
    ]


def test_adjacent_facets_are_a_separate_sweep_not_a_merged_url():
    """The crawler sweeps neighbouring subjects separately, so validation must
    check the same separate URLs — not one merged query the run never makes."""
    spec = registry.spec_for("euraxess")
    urls = spec.urls_for("astronomy")
    assert len(urls) == 2
    assert "job_research_field%3A34" in urls[0]
    assert urls[1].endswith("f%5B0%5D=job_research_field%3A345")   # Physics


def test_path_sources_build_one_url_per_slug():
    spec = registry.spec_for("academicjobsonline")
    assert spec.urls_for("astronomy") == [
        "https://academicjobsonline.org/ajo/physics/Astronomy",
        "https://academicjobsonline.org/ajo/physics/Astrophysics",
    ]


def test_keyword_boards_query_with_the_profiles_own_terms():
    """A general board has no per-field slug; the profile's keywords ARE the
    query, which is how changing your field changes what it asks for."""
    spec = registry.spec_for("jobs_ac_uk")
    urls = spec.urls_for(None, keywords=["radio astronomy"])
    assert len(urls) == 1
    assert "keywords=radio+astronomy" in urls[0]
    assert "jobTypeFacet%5B%5D=phds" in urls[0]


# --- the AJO fallback regression ------------------------------------------------

@pytest.mark.parametrize("field,expected", [
    ("mathematics", ["math", "stat"]),
    ("engineering", ["eng"]),
    ("economics", ["econ"]),
    ("geology", ["ES"]),
    ("geophysics_hydro", ["ES"]),
])
def test_ajo_uses_the_slugs_that_actually_exist(field, expected):
    """The five that were silently the fallback page.

    Verified live on 2026-08-15: /ajo/mathematics, /ajo/statistics,
    /ajo/economics, /ajo/engineering and /ajo/geosciences all return a page
    byte-identical to /ajo/zzz-not-a-real-category, while math, stat, econ,
    eng and ES each return their own listing (the page names the category in
    its heading: "Job Listings [ Engineering ]").
    """
    spec = registry.spec_for("academicjobsonline")
    assert list(spec.target(field).values) == expected


@pytest.mark.parametrize("dead", ["mathematics", "statistics", "economics",
                                  "engineering", "geosciences"])
def test_ajo_never_reintroduces_a_fallback_slug(dead):
    spec = registry.spec_for("academicjobsonline")
    for target in spec.fields.values():
        assert dead not in [str(v) for v in target.values], (
            f"{dead!r} is AcademicJobsOnline's generic fallback page, not a "
            f"category — it returns the wrong result set with a 200")


# --- profile override -----------------------------------------------------------

def test_profile_source_options_beat_the_registry():
    """A user must be able to correct a stale entry from their own YAML."""
    class Cfg:
        field_profile = "astronomy"
        def source_option(self, source, key):
            return ["chemistry"] if (source, key) == ("findaphd",
                                                      "disciplines") else None
    assert registry.values_for(Cfg(), "findaphd", "disciplines") == ["chemistry"]


def test_registry_is_used_when_the_profile_says_nothing():
    class Cfg:
        field_profile = "chemistry"
        def source_option(self, source, key):
            return None
    assert registry.values_for(Cfg(), "academicjobsonline",
                               "categories") == ["chemistry"]


# --- selector fixtures ----------------------------------------------------------
# Saved HTML from the live boards. If a board redesigns, these fail in CI
# instead of the crawler quietly returning zero.

@pytest.mark.parametrize("fixture,selector,minimum", [
    ("academicjobsonline_chemistry.html", "a[href*='/ajo/jobs/']", 3),
    ("euraxess_chemistry.html", "article.ecl-content-item", 3),
    ("jobs_ac_uk_phd.html", "div.j-search-result__result", 1),
    ("nature_careers.html", "a[href*='/naturecareers/job/']", 3),
    ("academictransfer.html", "a[href*='/en/jobs/']", 3),
])
def test_result_selector_still_matches_saved_markup(fixture, selector, minimum):
    from bs4 import BeautifulSoup
    from core.deps import _HTML_PARSER
    path = FIXTURES / fixture
    assert path.exists(), f"missing fixture {path}"
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), _HTML_PARSER)
    assert len(soup.select(selector)) >= minimum


def test_registered_selectors_match_the_fixture_selectors():
    """The registry's selector is what --validate-sources counts with, so it
    must be the same one the fixtures pin — otherwise the validator and the
    crawler are checking different things."""
    assert (registry.spec_for("academicjobsonline").result_selector
            == "a[href*='/ajo/jobs/']")
    assert (registry.spec_for("euraxess").result_selector
            == "article.ecl-content-item")
