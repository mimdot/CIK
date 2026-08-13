"""Sources build their QUERIES from the active field profile (Phase 1A / F2).

Four boards used to carry astronomy inside them, so they returned astronomy
results no matter which field was selected:

  * EURAXESS            hardcoded research-field facets 34/35/37
  * AcademicJobsOnline  hardcoded /ajo/physics/Astronomy category URLs
  * FindAPhD            hardcoded /phds/astrophysics/ listing URLs
  * LinkedIn            hardcoded ["PhD astronomy", ...] search phrases

Each now reads the profile. The astronomy assertions pin its queries to the
exact values it used before, so raising the other fields never lowers it.
"""

from __future__ import annotations

import argparse

import pytest

from core.config import build_config
from sources.academicjobsonline import ajo_categories_for
from sources.euraxess import (euraxess_adjacent_facets_for,
                              euraxess_facets_for)
from sources.findaphd import findaphd_disciplines_for
from sources.linkedin import LINKEDIN_KEYWORDS, linkedin_keywords_for


def _cfg(field=None, **overrides):
    ns = argparse.Namespace(field=field, no_config=True, **overrides)
    return build_config(ns)


SHIPPED = ["astronomy", "physics", "chemistry", "biology", "computer_science",
           "mathematics", "engineering", "economics", "geology",
           "condensed_matter", "geophysics_hydro"]


# --- astronomy is unchanged --------------------------------------------------

def test_astronomy_euraxess_facets_are_unchanged():
    """The three astro facets + the broad Physics PhD sweep, exactly as before."""
    cfg = _cfg("astronomy")
    assert euraxess_facets_for(cfg) == ["job_research_field:34",
                                        "job_research_field:35",
                                        "job_research_field:37"]
    assert euraxess_adjacent_facets_for(cfg) == ["job_research_field:345"]


def test_astronomy_ajo_and_findaphd_urls_are_unchanged():
    cfg = _cfg("astronomy")
    assert ajo_categories_for(cfg) == ["physics/Astronomy",
                                       "physics/Astrophysics"]
    assert findaphd_disciplines_for(cfg) == ["astrophysics", "astronomy"]


def test_astronomy_linkedin_queries_stay_astronomy():
    kws = linkedin_keywords_for(_cfg("astronomy"))
    assert kws and all("phd" in k.lower() or "postdoc" in k.lower()
                       for k in kws)
    joined = " ".join(kws).lower()
    assert "astronomy" in joined and "astrophysics" in joined


# --- other fields get their OWN queries --------------------------------------

@pytest.mark.parametrize("field,facet,category,discipline", [
    ("chemistry", "job_research_field:47", "chemistry", "chemistry"),
    ("biology", "job_research_field:38", "biology", "biological-sciences"),
    ("computer_science", "job_research_field:78", "cs", "computer-science"),
    ("mathematics", "job_research_field:298", "mathematics", "mathematics"),
    ("economics", "job_research_field:117", "economics", "economics"),
])
def test_each_field_queries_its_own_subject(field, facet, category,
                                            discipline):
    cfg = _cfg(field)
    assert facet in euraxess_facets_for(cfg)
    assert category in ajo_categories_for(cfg)
    assert discipline in findaphd_disciplines_for(cfg)


@pytest.mark.parametrize("field", [f for f in SHIPPED if f != "astronomy"])
def test_no_shipped_field_queries_astronomy_urls(field):
    """The headline regression: no astronomy string in another field's query."""
    cfg = _cfg(field)
    blob = " ".join([*ajo_categories_for(cfg), *findaphd_disciplines_for(cfg),
                     *linkedin_keywords_for(cfg)]).lower()
    assert "astro" not in blob, f"{field} still queries astronomy: {blob}"
    # 34/35/37 are the astronomy facets; physics(345) is legitimately shared.
    astro_facets = {"job_research_field:34", "job_research_field:35",
                    "job_research_field:37"}
    assert not (set(euraxess_facets_for(cfg)) & astro_facets)


@pytest.mark.parametrize("field", SHIPPED)
def test_every_shipped_field_has_real_queries(field):
    """Depth parity: no shipped field may be left with an empty board query."""
    cfg = _cfg(field)
    assert euraxess_facets_for(cfg), f"{field}: no EURAXESS facet"
    assert ajo_categories_for(cfg), f"{field}: no AJO category"
    assert findaphd_disciplines_for(cfg), f"{field}: no FindAPhD discipline"
    assert linkedin_keywords_for(cfg), f"{field}: no LinkedIn keywords"


# --- profile overrides + graceful fallbacks ----------------------------------

def test_source_options_override_the_builtin_map():
    cfg = _cfg("chemistry")
    cfg.source_options = {
        "euraxess": {"research_fields": [999]},
        "academicjobsonline": {"categories": ["custom/Cat"]},
        "findaphd": {"disciplines": ["custom-slug"]},
        "linkedin": {"keywords": ["PhD widget science"]},
    }
    assert euraxess_facets_for(cfg) == ["job_research_field:999"]
    assert ajo_categories_for(cfg) == ["custom/Cat"]
    assert findaphd_disciplines_for(cfg) == ["custom-slug"]
    assert linkedin_keywords_for(cfg) == ["PhD widget science"]


def test_unmapped_field_degrades_without_crashing():
    """A brand-new profile with no mapping must skip boards, not explode."""
    cfg = _cfg()
    cfg.field_profile = "underwater_basket_weaving"
    cfg.source_options = {}
    assert euraxess_facets_for(cfg) == []       # caller does a broad PhD sweep
    assert ajo_categories_for(cfg) == []        # caller skips the board
    assert findaphd_disciplines_for(cfg) == []
    assert linkedin_keywords_for(cfg)           # derived from search_terms


def test_linkedin_keywords_follow_search_terms_and_position_type():
    cfg = _cfg()
    cfg.search_terms = ["marine biology"]
    cfg.source_options = {}
    cfg.wanted_types = ["phd"]
    assert linkedin_keywords_for(cfg) == ["PhD marine biology"]
    cfg.wanted_types = ["phd", "postdoc"]
    assert linkedin_keywords_for(cfg) == ["PhD marine biology",
                                          "Postdoc marine biology"]


def test_linkedin_falls_back_when_profile_has_no_terms():
    cfg = _cfg()
    cfg.search_terms = []
    cfg.source_options = {}
    assert linkedin_keywords_for(cfg) == LINKEDIN_KEYWORDS


def test_ajo_and_findaphd_return_empty_list_not_none():
    """Sources check truthiness to decide whether to skip — keep it a list."""
    cfg = _cfg()
    cfg.field_profile = "nope"
    cfg.source_options = {}
    assert isinstance(ajo_categories_for(cfg), list)
    assert isinstance(findaphd_disciplines_for(cfg), list)
