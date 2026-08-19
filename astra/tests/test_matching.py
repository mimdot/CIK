#!/usr/bin/env python3
"""Tests for the matching engine (Sprint 03, Track B).

Golden-set fixtures per the spec:
- High-match opportunity (same domain, same methods, preferred country)
  -> overall score > 0.8
- Low-match opportunity (different domain, different country) -> score < 0.3
- Edge cases: empty methods -> method_score 0.5 (neutral); opportunity with no
  country -> location_score 0.5 (neutral).
- Explanation strings carry the domain name and the profile's methods.
"""

from __future__ import annotations

import argparse

import pytest

from core.config import build_config
from core.profile_schema import UserProfile
from core.records import make_record
from matching import (LOCATION_WEIGHT, METHOD_WEIGHT, NEUTRAL, TOPIC_WEIGHT,
                      MatchResult, explain_match, location_score, method_score,
                      next_actions, score_match, topic_score)

import astra as P


def _cfg():
    return build_config(argparse.Namespace(no_config=True))


# A realistic profile: astronomy / interstellar medium, radio methods.
PROFILE = UserProfile(
    domain="astronomy",
    subfield="interstellar medium",
    methods=["radio interferometry", "MHD simulation"],
    tools=["LOFAR", "Python"],
    skills=["dust polarization", "faraday tomography"],
    experience_level="phd_student",
    target_roles=["postdoc"],
    countries_preferred=["Germany", "Netherlands"],
    constraints=["must be funded"],
    confidence=0.85,
    raw_text="cv text",
)


def _high_opp():
    return make_record(
        title="PhD position in interstellar medium radio astronomy",
        institution="Max Planck Institute for Radio Astronomy",
        country="Germany",
        deadline="2099-01-01",
        url="https://ex.org/jobs/high",
        short_description="Radio interferometry (LOFAR) and MHD simulations of "
                          "magnetic fields in molecular clouds; faraday "
                          "tomography of dust polarization.",
        source="aas")


def _low_opp():
    return make_record(
        title="Postdoc in developmental neuroscience",
        institution="University of California",
        country="United States",
        deadline="2099-01-01",
        url="https://ex.org/jobs/low",
        short_description="Cell biology of neural development, mouse models, "
                          "immunohistochemistry.",
        source="nature_careers")


# ---------------------------------------------------------------------------
# B7 golden set
# ---------------------------------------------------------------------------
def test_high_match_scores_above_08():
    result = score_match(PROFILE, _high_opp(), _cfg())
    assert result.overall_score > 0.8
    assert result.topic_score > 0.7
    assert result.location_score == 1.0


def test_low_match_scores_below_03():
    result = score_match(PROFILE, _low_opp(), _cfg())
    assert result.overall_score < 0.3
    assert result.topic_score < 0.3


def test_high_match_explanation_mentions_domain_and_methods():
    result = score_match(PROFILE, _high_opp(), _cfg())
    assert "astronomy" in result.explanation
    assert "radio interferometry" in result.explanation


def test_match_result_is_dataclass_with_expected_fields():
    result = score_match(PROFILE, _high_opp(), _cfg())
    assert isinstance(result, MatchResult)
    for attr in ("overall_score", "topic_score", "method_score",
                 "location_score", "explanation", "confidence"):
        assert hasattr(result, attr)
    assert result.confidence == PROFILE.confidence


# ---------------------------------------------------------------------------
# topic dimension
# ---------------------------------------------------------------------------
def test_topic_strong_title_match():
    opp = make_record(title="PhD on interstellar medium magnetic fields",
                      institution="X", source="aas",
                      short_description="Faraday tomography of molecular clouds.")
    assert topic_score(PROFILE, opp, _cfg()) >= 0.9


def test_topic_desc_only_match_partial():
    opp = make_record(title="Research position",
                      institution="X", source="aas",
                      short_description="Study of the interstellar medium and "
                                        "magnetic fields in galaxies.")
    s = topic_score(PROFILE, opp, _cfg())
    assert 0.0 < s <= NEUTRAL          # desc-only anchors: partial, not full


def test_topic_unrelated_is_zero():
    opp = make_record(title="PhD in marine biology", institution="X",
                      source="aas",
                      short_description="Coral reef ecology.")
    assert topic_score(PROFILE, opp, _cfg()) == 0.0


def test_topic_empty_text_is_zero():
    assert topic_score(PROFILE, make_record(title="", institution="X"), _cfg()) == 0.0


def test_topic_works_for_any_domain():
    marine = UserProfile(domain="marine biology", subfield="coral reef")
    opp = make_record(title="PhD in coral reef ecology", institution="X",
                      source="aas", short_description="Bleaching studies.")
    assert topic_score(marine, opp, _cfg()) >= 0.9


def test_topic_ignores_constraints():
    constrained = UserProfile(domain="astronomy", subfield="interstellar medium",
                              constraints=["no night shifts"])
    opp = make_record(title="PhD in interstellar medium", institution="X",
                      source="aas", short_description="")
    assert topic_score(constrained, opp, _cfg()) >= 0.9


# ---------------------------------------------------------------------------
# method dimension
# ---------------------------------------------------------------------------
def test_method_all_terms_match():
    opp = make_record(title="PhD using radio interferometry", institution="X",
                      source="aas",
                      short_description="LOFAR MHD simulations in Python.")
    assert method_score(PROFILE, opp) == 1.0


def test_method_partial_overlap():
    opp = make_record(title="PhD using radio interferometry", institution="X",
                      source="aas",
                      short_description="Single-dish observations.")
    s = method_score(PROFILE, opp)
    assert 0.0 < s < 1.0


def test_method_no_terms_matched():
    opp = make_record(title="PhD in medieval history", institution="X",
                      source="aas", short_description="Parchment analysis.")
    assert method_score(PROFILE, opp) == 0.0


def test_method_empty_profile_returns_neutral():
    bare = UserProfile(domain="astronomy")
    opp = make_record(title="anything", institution="X", source="aas")
    assert method_score(bare, opp) == NEUTRAL


# ---------------------------------------------------------------------------
# location dimension
# ---------------------------------------------------------------------------
def test_location_preferred_country_is_one():
    opp = make_record(title="t", institution="X", country="Germany", source="aas")
    assert location_score(PROFILE, opp) == 1.0


def test_location_no_country_is_neutral():
    opp = make_record(title="t", institution="X", source="aas")
    assert location_score(PROFILE, opp) == NEUTRAL


def test_location_no_preference_is_neutral():
    open_profile = UserProfile(domain="astronomy")
    opp = make_record(title="t", institution="X", country="Germany", source="aas")
    assert location_score(open_profile, opp) == NEUTRAL


def test_location_blocked_constraint_is_zero():
    constrained = UserProfile(domain="astronomy", countries_preferred=["Germany"],
                              constraints=["united states"])
    opp = make_record(title="t", institution="X", country="United States", source="aas")
    assert location_score(constrained, opp) == 0.0


def test_location_known_not_preferred_is_low():
    opp = make_record(title="t", institution="X", country="Japan", source="aas")
    assert location_score(PROFILE, opp) < NEUTRAL


def test_location_alias_country_matches():
    opp = make_record(title="t", institution="X", country="Deutschland", source="aas")
    assert location_score(PROFILE, opp) == 1.0


# ---------------------------------------------------------------------------
# explanation
# ---------------------------------------------------------------------------
def test_explain_mentions_missing_skills():
    opp = make_record(title="PhD in interstellar medium", institution="X",
                      source="aas",
                      short_description="Radio observations of the ISM.")
    result = score_match(PROFILE, opp, _cfg())
    assert "MHD simulation" in result.explanation  # a method not mentioned


def test_explain_low_match_is_candid():
    result = score_match(PROFILE, _low_opp(), _cfg())
    assert "outside your primary field" in result.explanation


def test_explain_location_blocked():
    constrained = UserProfile(domain="astronomy", countries_preferred=["Germany"],
                              constraints=["united states"])
    result = score_match(constrained, _low_opp(), _cfg())
    assert "conflicts with your constraints" in result.explanation


# ---------------------------------------------------------------------------
# weighting / determinism
# ---------------------------------------------------------------------------
def test_overall_is_weighted_blend():
    opp = make_record(title="PhD in interstellar medium", institution="X",
                      country="Germany", source="aas",
                      short_description="Radio interferometry")
    result = score_match(PROFILE, opp, _cfg())
    expected = (TOPIC_WEIGHT * result.topic_score
                + METHOD_WEIGHT * result.method_score
                + LOCATION_WEIGHT * result.location_score)
    assert abs(result.overall_score - expected) < 1e-3
    # the blend really moves the final number
    assert result.overall_score != result.topic_score


def test_score_match_deterministic():
    a = score_match(PROFILE, _high_opp(), _cfg())
    b = score_match(PROFILE, _high_opp(), _cfg())
    assert a == b


def test_weights_sum_to_one():
    assert abs(TOPIC_WEIGHT + METHOD_WEIGHT + LOCATION_WEIGHT - 1.0) < 1e-9


def test_weights_are_in_valid_range():
    for w in (TOPIC_WEIGHT, METHOD_WEIGHT, LOCATION_WEIGHT):
        assert 0.0 < w < 1.0


# ---------------------------------------------------------------------------
# monolith re-export + pipeline wiring
# ---------------------------------------------------------------------------
def test_monolith_reexports_matching_names():
    assert P.score_match is not None
    assert P.topic_score is not None
    assert P.MatchResult is not None
    assert callable(P.score_match)


def test_run_scores_when_profile_given(tmp_path):
    cfg = _cfg()
    cfg.output_path = str(tmp_path / "results.csv")
    cfg.countries = ["*"]
    cfg.wanted_types = ["phd"]
    cfg.keep_ambiguous = True
    cfg.exclude_expired = True
    cfg.write_html = False
    from pipeline.run import run
    records = run(cfg, injected_raw=[_high_opp(), _low_opp()], profile=PROFILE)
    assert all(r.get("match_score") is not None for r in records)
    assert all(r.get("match_explanation") for r in records)
    scores = [r["match_score"] for r in records]
    assert scores == sorted(scores, reverse=True)     # sorted by match score
    assert records[0]["title"].startswith("PhD position in interstellar")


def test_run_without_profile_has_no_match_fields(tmp_path):
    cfg = _cfg()
    cfg.output_path = str(tmp_path / "results2.csv")
    cfg.countries = ["*"]
    cfg.wanted_types = ["phd"]
    cfg.keep_ambiguous = True
    cfg.exclude_expired = True
    cfg.write_html = False
    from pipeline.run import run
    records = run(cfg, injected_raw=[_high_opp()])
    assert records[0].get("match_score") is None
    import json
    with open(cfg.json_path, "r", encoding="utf-8") as fh:
        rows = json.load(fh)
    assert "match_score" in rows[0]
    assert rows[0]["match_score"] is None


# --- Sprint 09 A4: deterministic next_actions --------------------------------
def test_next_actions_apply_by_deadline():
    actions = next_actions(PROFILE, _high_opp())
    assert any(a.startswith("Apply by") for a in actions)


def test_next_actions_funding_note():
    opp = _high_opp()
    opp["funding_status"] = "fully funded"
    actions = next_actions(PROFILE, opp)
    assert any("fully funded" in a for a in actions)
    opp["funding_status"] = "unknown"
    actions = next_actions(PROFILE, opp)
    assert any(a == "Check funding details" for a in actions)


def test_next_actions_strengthen_missing_methods():
    # An opportunity that advertises none of the profile's methods/tools.
    opp = make_record(
        title="PhD in stellar dynamics",
        institution="Leiden Observatory",
        country="Netherlands",
        deadline="2099-01-01",
        short_description="N-body simulations of stellar clusters; "
                          "no radio, no LOFAR, no MHD.",
        source="aas")
    actions = next_actions(PROFILE, opp)
    strengthen = [a for a in actions if a.startswith("Strengthen:")]
    assert strengthen, actions
    assert any(m in strengthen[0] for m in ("radio interferometry", "MHD"))


def test_next_actions_relocation_note():
    actions = next_actions(PROFILE, _low_opp())   # United States, not preferred
    assert any(a.startswith("Requires relocation") for a in actions)


def test_next_actions_no_relocation_when_preferred_country():
    opp = make_record(title="PhD in ISM", institution="AIP",
                      country="Germany", deadline="2099-01-01",
                      short_description="Radio work on magnetic fields.",
                      source="aas")
    actions = next_actions(PROFILE, opp)
    assert not any(a.startswith("Requires relocation") for a in actions)


def test_next_actions_generic_fallback():
    bare = {"title": "", "short_description": "", "institution": "",
            "country": ""}
    actions = next_actions(PROFILE, bare)
    assert actions == ["Review the posting and prepare your application"]


def test_next_actions_strengthen_only_when_posting_has_text():
    title_only = {"title": "PhD position", "short_description": "",
                  "institution": "", "country": ""}
    actions = next_actions(PROFILE, title_only)
    assert any(a.startswith("Strengthen:") for a in actions)
