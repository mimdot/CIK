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
           "condensed_matter", "geophysics_hydro",
           # batch 1, added 2026-08-20
           "neuroscience", "biomedical_sciences", "environmental_science",
           "materials_science", "statistics_data_science"]

# Slugs AcademicJobsOnline serves its GENERIC FALLBACK listing for. The board
# answers 200 for any path, so each of these looks healthy while returning the
# wrong result set entirely — that is what made the original bug survive months
# of green tests. Probed against the fallback fingerprint on 2026-08-20.
AJO_FALLBACK_SLUGS = {"mathematics", "statistics", "economics", "engineering",
                      "geosciences", "neuroscience", "medicine", "materials",
                      "mat", "bio"}


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
    # Bare "astrophysics"/"astronomy" were never real FindAPhD addresses —
    # confirmed live 2026-08-16: /phds/astronomy/ with no token is FindAPhD's
    # own 404. Real entries carry the durable per-discipline token the site
    # embeds in its own rendered links (see url_registry.yaml's findaphd note).
    assert findaphd_disciplines_for(cfg) == ["astronomy/?30M7W2o3",
                                             "astrophysics/?30M7Wyo3"]


def test_astronomy_linkedin_queries_stay_astronomy():
    kws = linkedin_keywords_for(_cfg("astronomy"))
    assert kws and all("phd" in k.lower() or "postdoc" in k.lower()
                       for k in kws)
    joined = " ".join(kws).lower()
    assert "astronomy" in joined and "astrophysics" in joined


# --- other fields get their OWN queries --------------------------------------

@pytest.mark.parametrize("field,facet,category,discipline", [
    ("chemistry", "job_research_field:47", "chemistry", "chemistry/?10M7c0"),
    ("biology", "job_research_field:38", "biology", "biological-sciences/?10M780"),
    ("computer_science", "job_research_field:78", "cs", "computer-science/?10M7g0"),
    # "mathematics" and "economics" stood here until 2026-08-20 and passed,
    # because the stale source_options block in each field YAML overrode the
    # registry — so the test asserted the very fallback slugs url_registry.yaml
    # documents as the original bug. The overrides are gone; these are the real
    # slugs. See AJO_FALLBACK_SLUGS below.
    ("mathematics", "job_research_field:298", "math", "mathematics/?10M7O0"),
    ("economics", "job_research_field:117", "econ", "economics/?10M7k0"),
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


# Fields with no FindAPhD discipline token yet. The tokens are opaque strings
# ("chemistry/?10M7c0") that can only be read off FindAPhD's own rendered
# discipline links — they are not derivable from the slug, and a guessed one
# silently returns the site's 404. On 2026-08-20 the site answered 403 to every
# automated fetch (the Cloudflare block SOURCE_HEALTH.md records), so the batch
# added that day could not obtain them. The practical cost today is nil:
# findaphd returns 0 records for EVERY field under that same block. Empty this
# set once the tokens can be read again.
FINDAPHD_PENDING = {"neuroscience", "biomedical_sciences",
                    "environmental_science", "materials_science",
                    "statistics_data_science"}


@pytest.mark.parametrize("field", SHIPPED)
def test_every_shipped_field_has_real_queries(field):
    """Depth parity: no shipped field may be left with an empty board query."""
    cfg = _cfg(field)
    assert euraxess_facets_for(cfg), f"{field}: no EURAXESS facet"
    assert ajo_categories_for(cfg), f"{field}: no AJO category"
    if field not in FINDAPHD_PENDING:
        assert findaphd_disciplines_for(cfg), f"{field}: no FindAPhD discipline"
    assert linkedin_keywords_for(cfg), f"{field}: no LinkedIn keywords"


def test_findaphd_pending_list_names_only_real_fields():
    """Guard the guard: a typo here would silently excuse nothing."""
    assert FINDAPHD_PENDING <= set(SHIPPED)


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


# --- the drift guard ---------------------------------------------------------

@pytest.mark.parametrize("field", SHIPPED)
def test_no_field_targets_an_ajo_fallback_slug(field):
    """No shipped field may point AcademicJobsOnline at its fallback page.

    This is the regression that already happened once and survived because the
    board answers 200 for anything: url_registry.yaml was corrected, the stale
    per-field ``source_options`` overrides were not, and five fields went on
    quietly scraping the generic listing. Asserting on the resolved value
    catches it from either home.
    """
    for category in ajo_categories_for(_cfg(field)):
        assert category.split("/")[0] not in AJO_FALLBACK_SLUGS, (
            f"{field} targets AJO category {category!r}, which serves the "
            f"generic fallback listing — see url_registry.yaml's note")


@pytest.mark.parametrize("field", SHIPPED)
def test_no_field_redefines_ajo_categories_in_its_yaml(field):
    """AJO categories live in url_registry.yaml and nowhere else.

    ``source_options`` silently WINS over the registry, so a duplicate here is
    not a harmless restatement — it is the drift mechanism itself. Fields added
    from 2026-08-20 carry no such block; the older ones that still do are
    pinned to the registry's value by the test above.
    """
    from core.config import load_field_profile
    profile = load_field_profile(field) or {}
    block = (profile.get("source_options") or {}).get("academicjobsonline")
    if block is None:
        return
    registry_value = ajo_categories_for(_cfg(field))
    assert list(block.get("categories") or []) == registry_value, (
        f"fields/{field}.yaml redefines academicjobsonline.categories and has "
        f"drifted from the registry — delete the block, do not re-sync it")


@pytest.mark.parametrize("field", [f for f in SHIPPED if f != "astronomy"])
def test_no_field_silently_inherits_astronomys_departments(field):
    """The department sweep is the fourth board that used to carry astronomy.

    ``source_uni_departments`` falls back to the built-in 150-site astronomy
    registry for any profile with NO ``departments:`` key, so simply omitting
    the block makes a chemistry or neuroscience run crawl astronomy department
    pages — slowly, and for nothing. A profile must either curate its own list
    or declare an explicit empty one, which disables the source cleanly.
    """
    from core.config import apply_field_profile, load_field_profile
    cfg = _cfg(field)
    apply_field_profile(cfg, load_field_profile(field))
    assert cfg.departments_explicit, (
        f"fields/{field}.yaml has no `departments:` key, so it inherits the "
        f"astronomy registry — add a curated list or `departments: []`")
