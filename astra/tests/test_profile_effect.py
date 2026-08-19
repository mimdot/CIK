#!/usr/bin/env python3
"""Does the research profile actually change anything?

The reported doubt — "I cannot tell whether my selections change anything" —
was justified for the dashboard and the desktop app. ``pipeline_run`` has
always accepted a ``profile`` and scored every kept opportunity against it, but
only the CLI ever passed one: ``core.tasks.run_pipeline_job`` (the ONLY path the
UI uses) called it without. So the profile page collected keywords, saved them,
and the engine never saw them.

These tests hold the whole chain down:
  * a profile reaches the engine from the job entrypoint, and its terms are
    reported back so the UI can show them;
  * two different profiles over the SAME fixture data produce different
    orderings and different scores;
  * different fields select different sources;
  * the opportunity cache is keyed by profile, so changing it cannot be masked
    by a stale cached list.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile

import pytest

from core import cache
from core.config import build_config
from core.profile_schema import UserProfile
from core.records import make_record
from core.tasks import profile_terms
from pipeline.run import run as pipeline_run
from sources.base import resolve_sources_for_field


# --- fixture corpus ------------------------------------------------------------

def _corpus():
    """One radio-astronomy post and one exoplanet post, both valid astronomy."""
    return [
        # NB: the title deliberately avoids the bare word "astronomy" — see
        # test_domain_word_in_a_title_matches_any_profile_of_that_domain.
        make_record(title="PhD in Interstellar Medium Studies",
                    url="https://x/radio",
                    short_description="radio astronomy interferometry LOFAR "
                                      "interstellar medium dust polarization",
                    source="euraxess", country="Germany"),
        make_record(title="PhD in Exoplanet Atmospheres",
                    url="https://x/exo",
                    short_description="exoplanet atmospheres transit "
                                      "spectroscopy planetary science",
                    source="euraxess", country="Germany"),
    ]


def _radio_profile():
    return UserProfile(domain="astronomy", subfield="interstellar medium",
                       methods=["radio interferometry"], tools=["LOFAR"],
                       skills=["dust polarization"], experience_level="msc",
                       target_roles=["phd"], confidence=0.9, raw_text="x")


def _exo_profile():
    return UserProfile(domain="astronomy", subfield="exoplanets",
                       methods=["transit spectroscopy"], tools=["JWST"],
                       skills=["planetary atmospheres"], experience_level="msc",
                       target_roles=["phd"], confidence=0.9, raw_text="x")


def _cfg(tmp, field="astronomy"):
    cfg = build_config(argparse.Namespace(field=field, no_config=True))
    cfg.output_path = os.path.join(tmp, f"pos_{field}")
    cfg.write_html = False
    cfg.state_file = os.path.join(tmp, f".seen_{field}.json")
    return cfg


@pytest.fixture
def tmp_run():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


# --- the profile reaches the engine --------------------------------------------

def test_two_profiles_rank_the_same_corpus_differently(tmp_run):
    """THE regression. Same data, two profiles, different answers."""
    def ranked(profile):
        cfg = _cfg(tmp_run)
        kept = pipeline_run(cfg, injected_raw=_corpus(), profile=profile)
        return [(r["title"], r.get("match_score")) for r in kept]

    radio = ranked(_radio_profile())
    exo = ranked(_exo_profile())

    assert radio and exo, "the corpus must survive the field filter"
    # Each profile puts ITS topic first.
    assert "Interstellar" in radio[0][0], f"radio profile ranked {radio}"
    assert "Exoplanet" in exo[0][0], f"exoplanet profile ranked {exo}"
    # And the scores genuinely differ — not just a reshuffle of equal numbers.
    assert dict(radio) != dict(exo)


def test_every_record_gets_a_score_and_an_explanation(tmp_run):
    cfg = _cfg(tmp_run)
    kept = pipeline_run(cfg, injected_raw=_corpus(), profile=_radio_profile())
    for rec in kept:
        assert isinstance(rec.get("match_score"), (int, float))
        assert rec.get("match_explanation")


def test_without_a_profile_nothing_is_scored(tmp_run):
    """The control: the difference above is the profile, not the pipeline."""
    cfg = _cfg(tmp_run)
    kept = pipeline_run(cfg, injected_raw=_corpus(), profile=None)
    assert kept
    # match_score is part of the record schema (make_record seeds it as None);
    # what must be absent is a VALUE.
    assert all(r.get("match_score") is None for r in kept)
    assert all(not r.get("match_explanation") for r in kept)


def test_run_pipeline_job_passes_the_active_profile(tmp_run, monkeypatch):
    """The break that caused the bug: the UI's entrypoint dropped the profile.

    Everything above passes a profile by hand. This asserts the path the
    dashboard and desktop app ACTUALLY use does too.
    """
    from core import tasks as tasks_module

    monkeypatch.chdir(tmp_run)
    monkeypatch.setattr("db.init.resolve_db_url",
                        lambda: f"sqlite:///{tmp_run}/t.db")
    monkeypatch.setattr(tasks_module, "_active_profile", _radio_profile)

    seen: dict = {}

    def capture(cfg, only_sources=None, on_progress=None, funnel=None,
                cancel=None, profile=None, **kw):
        seen["profile"] = profile
        with open(cfg.json_path, "w", encoding="utf-8") as fh:
            json.dump([], fh)
        return []

    monkeypatch.setattr(tasks_module, "pipeline_run", capture)
    events: list[dict] = []
    tasks_module.run_pipeline_job(field="astronomy",
                                  on_progress=lambda e: events.append(e))

    assert seen["profile"] is not None, (
        "run_pipeline_job must hand the active profile to the engine — "
        "without this the profile page changes nothing")
    assert seen["profile"].subfield == "interstellar medium"

    # ...and it must report which terms it used, so the UI can show them.
    funnel = [e for e in events if e.get("event") == "funnel"][0]
    assert funnel["profile_active"] is True
    assert "LOFAR" in funnel["profile_terms"]


def test_profile_terms_are_ordered_and_deduplicated():
    p = UserProfile(domain="astronomy", subfield="ism",
                    methods=["radio", "radio"], tools=["LOFAR"], skills=[],
                    raw_text="x")
    assert profile_terms(p) == ["ism", "radio", "LOFAR"]
    assert profile_terms(None) == []


# --- source selection ----------------------------------------------------------

def test_different_fields_select_different_sources():
    """Choosing a field must change WHICH boards are crawled, not only scoring.

    AAS is registered as an astronomy specialist, so a chemistry run must not
    hit it — that is the other half of "my profile has no effect".
    """
    enabled = {"aas": True, "euraxess": True, "findaphd": True,
               "academicjobsonline": True}
    astro = resolve_sources_for_field("astronomy", enabled,
                                      known_sources=list(enabled))
    chem = resolve_sources_for_field("chemistry", enabled,
                                     known_sources=list(enabled))
    assert astro != chem
    assert astro["aas"] is True
    assert chem["aas"] is False
    # The general boards stay on for both.
    assert astro["euraxess"] is chem["euraxess"] is True


# --- the cache -----------------------------------------------------------------

def test_opportunity_cache_is_keyed_by_profile():
    """A list ranked under one profile must never be served for another."""
    radio = cache.profile_fingerprint(profile_terms(_radio_profile()))
    exo = cache.profile_fingerprint(profile_terms(_exo_profile()))
    assert radio != exo
    assert cache.opportunity_list_key("astronomy", radio) != \
        cache.opportunity_list_key("astronomy", exo)


def test_cached_list_does_not_bleed_between_profiles():
    radio = cache.profile_fingerprint(profile_terms(_radio_profile()))
    exo = cache.profile_fingerprint(profile_terms(_exo_profile()))
    cache.invalidate_opportunities()
    try:
        cache.cache_opportunity_list([{"title": "radio row"}], "astronomy", radio)
        assert cache.get_cached_opportunity_list("astronomy", exo) is None
        assert cache.get_cached_opportunity_list("astronomy", radio) == \
            [{"title": "radio row"}]
    finally:
        cache.invalidate_opportunities()


def test_fingerprint_ignores_keyword_order_but_not_content():
    assert cache.profile_fingerprint(["a", "b"]) == \
        cache.profile_fingerprint(["b", "a"])
    assert cache.profile_fingerprint(["a", "b"]) != \
        cache.profile_fingerprint(["a", "c"])
    assert cache.profile_fingerprint([]) == "none"


def test_legacy_unkeyed_call_still_means_what_it_did():
    assert cache.opportunity_list_key() == "opportunities:list"


def test_domain_word_in_a_title_matches_any_profile_of_that_domain():
    """Characterizes a real weakness in topic scoring, found while proving the
    profile chain — NOT an endorsement of it.

    The profile's ``domain`` is scored as if it were one of the user's topic
    terms, so a post whose title merely contains the field name earns a topic
    match from every profile in that field. With a corpus of
    "PhD in Radio Astronomy" vs "PhD in Exoplanet Atmospheres", an EXOPLANET
    profile ranks the radio post first (0.350 vs 0.275) purely because
    "Astronomy" is in its title.

    Left as-is deliberately: retuning the matcher is a separate change with its
    own blast radius. Pinned here so it is a known, visible property rather
    than a surprise, and so a future fix has a test to flip.
    """
    import argparse as _argparse
    from matching import score_match
    cfg = build_config(_argparse.Namespace(field="astronomy", no_config=True))
    titled = {"title": "PhD in Radio Astronomy",
              "short_description": "radio astronomy interferometry",
              "country": "Germany"}
    untitled = {"title": "PhD in Stellar Winds",
                "short_description": "radio astronomy interferometry",
                "country": "Germany"}
    exo = _exo_profile()
    assert score_match(exo, titled, cfg).topic_score > \
        score_match(exo, untitled, cfg).topic_score
