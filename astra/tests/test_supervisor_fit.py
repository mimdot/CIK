"""Explainable, calibrated supervisor fit (Phase 4B/4C).

``fit_score`` used to be the raw ranking number — roughly h-index plus a bonus
per paper. Unbounded, not comparable across fields or backends, and with no
statement anywhere of how it was reached: "the fit value is very strange and
not adjusted / not usable".

It is now a weighted sum of four bounded components (topic 40, recency 25,
seniority 20, country 15), always 0-100, returned with its own reasoning.
"""

from __future__ import annotations

import statistics

import pytest

from supervisors.fit import (RECENCY_SATURATION, WRONG_COUNTRY_PENALTY,
                             compute_fit, country_component,
                             passes_relevance_gate, recency_component,
                             seniority_component, topic_component)

ASTRO_KEYWORDS = ["radio astronomy", "interstellar medium", "star formation",
                  "molecular cloud"]


def candidate(topics="", papers=0, senior=0, country="Germany", **extra):
    row = {
        "name": "Dr Test",
        "topics": topics,
        "representative_papers": topics,
        "papers": papers,
        "last_author_papers": senior,
        "country": country,
        "institution": "Some University",
    }
    row.update(extra)
    return row


# --- the scale is real ---------------------------------------------------------

@pytest.mark.parametrize("papers,senior,topics,country", [
    (14, 9, "; ".join(ASTRO_KEYWORDS), "Germany"),
    (0, 0, "", "France"),
    (1, 0, ASTRO_KEYWORDS[0], "unverified"),
    (500, 500, "; ".join(ASTRO_KEYWORDS), "Germany"),
])
def test_score_is_always_between_0_and_100(papers, senior, topics, country):
    fit = compute_fit(candidate(topics, papers, senior, country),
                      ASTRO_KEYWORDS, "Germany")
    assert 0.0 <= fit["fit_score"] <= 100.0


def test_a_perfect_candidate_scores_100():
    fit = compute_fit(
        candidate("; ".join(ASTRO_KEYWORDS), papers=20, senior=15,
                  country="Germany"),
        ASTRO_KEYWORDS, "Germany")
    assert fit["fit_score"] == 100.0


def test_an_empty_candidate_scores_near_zero():
    fit = compute_fit(candidate("", papers=0, senior=0, country="unverified"),
                      ASTRO_KEYWORDS, "Germany")
    assert fit["fit_score"] < 10.0


# --- it is EXPLAINABLE ---------------------------------------------------------

def test_every_score_carries_its_reasoning():
    fit = compute_fit(
        candidate("; ".join(ASTRO_KEYWORDS[:2]), papers=9, senior=5),
        ASTRO_KEYWORDS, "Germany")
    assert set(fit["fit_breakdown"]) == {"topic", "recency", "seniority",
                                         "country"}
    for part in fit["fit_breakdown"].values():
        assert {"value", "weight", "points"} <= set(part)
    # The points must actually add up to the score.
    total = sum(p["points"] for p in fit["fit_breakdown"].values())
    assert abs(total - fit["fit_score"]) < 0.5


def test_the_explanation_names_the_matched_terms():
    fit = compute_fit(candidate("radio astronomy; star formation", papers=6,
                                senior=3), ASTRO_KEYWORDS, "Germany")
    assert "radio astronomy" in fit["fit_explanation"]
    assert set(fit["fit_matched_terms"]) == {"radio astronomy",
                                             "star formation"}
    assert "pts" in fit["fit_explanation"]


def test_the_explanation_says_why_a_score_is_low():
    fit = compute_fit(candidate("medieval poetry", papers=1, senior=0,
                                country="France"),
                      ASTRO_KEYWORDS, "Germany")
    text = fit["fit_explanation"]
    assert "none of your keywords" in text
    assert "not in Germany" in text or "not Germany" in text


# --- CALIBRATION: scores must spread, not cluster -----------------------------

def _mixed_pool(country="Germany"):
    return [
        candidate("; ".join(ASTRO_KEYWORDS), 14, 9, country),        # ideal PI
        candidate("; ".join(ASTRO_KEYWORDS[:2]), 9, 5, country),     # strong
        candidate("; ".join(ASTRO_KEYWORDS[:2]), 11, 0, country),    # postdoc
        candidate(ASTRO_KEYWORDS[0], 5, 2, country),                 # mid
        candidate(ASTRO_KEYWORDS[0], 2, 2, country),                 # quiet
        candidate("; ".join(ASTRO_KEYWORDS), 12, 8, "France"),       # elsewhere
        candidate("medieval poetry", 10, 6, country),                # off-field
        candidate("; ".join(ASTRO_KEYWORDS[:2]), 6, 3, "unverified"),
    ]


@pytest.mark.parametrize("signal", ["last_author", "corresponding", "none"])
def test_scores_spread_across_the_range(signal):
    """The brief: calibrate so scores spread instead of clustering. An earlier
    threshold gave one keyword hit out of four a perfect topic score, which
    squashed everyone into the top quarter."""
    scores = [compute_fit(c, ASTRO_KEYWORDS, "Germany", signal)["fit_score"]
              for c in _mixed_pool()]
    assert max(scores) - min(scores) > 50, f"too clustered: {sorted(scores)}"
    assert statistics.pstdev(scores) > 15


def test_a_researcher_in_the_wrong_country_ranks_last():
    """They cannot supervise you — output and seniority must not carry them."""
    pool = _mixed_pool()
    scored = sorted(
        ((c, compute_fit(c, ASTRO_KEYWORDS, "Germany")["fit_score"])
         for c in pool), key=lambda kv: -kv[1])
    assert scored[-1][0]["country"] == "France"


def test_the_wrong_country_penalty_is_applied_and_declared():
    local = compute_fit(candidate("; ".join(ASTRO_KEYWORDS), 12, 8, "Germany"),
                        ASTRO_KEYWORDS, "Germany")
    abroad = compute_fit(candidate("; ".join(ASTRO_KEYWORDS), 12, 8, "France"),
                         ASTRO_KEYWORDS, "Germany")
    assert abroad["fit_wrong_country"] is True
    assert local["fit_wrong_country"] is False
    assert abroad["fit_score"] < local["fit_score"] * WRONG_COUNTRY_PENALTY * 1.2


# --- recency beats lifetime output --------------------------------------------

def test_recent_output_is_what_counts():
    assert recency_component(0) == 0.0
    assert recency_component(RECENCY_SATURATION) == 1.0
    assert recency_component(RECENCY_SATURATION * 10) == 1.0, "must saturate"
    assert recency_component(RECENCY_SATURATION // 2) == pytest.approx(0.5, abs=0.1)


def test_seniority_rewards_being_the_pi():
    """Half of recent papers as senior author is a full PI signal."""
    assert seniority_component(0, 10) == 0.0
    assert seniority_component(5, 10) == 1.0
    assert seniority_component(10, 10) == 1.0
    assert seniority_component(0, 0) == 0.0          # no papers, no crash


def test_alphabetical_fields_do_not_score_seniority():
    """Economics orders authors alphabetically — last-author means nothing, so
    the weight is redistributed instead of scoring everyone zero."""
    assert seniority_component(0, 10, signal="none") is None
    fit = compute_fit(candidate("; ".join(ASTRO_KEYWORDS), 12, 0),
                      ASTRO_KEYWORDS, "Germany", senior_signal="none")
    assert "seniority" not in fit["fit_breakdown"]
    assert "alphabetically" in fit["fit_explanation"]
    # The remaining components still reach the full 100.
    assert fit["fit_score"] == pytest.approx(100.0, abs=0.5)


# --- components in isolation ---------------------------------------------------

def test_topic_component_needs_real_coverage():
    value, matched = topic_component(ASTRO_KEYWORDS, "radio astronomy only")
    assert matched == ["radio astronomy"]
    assert value < 0.6, "one of four terms is not a strong topic match"
    full, _ = topic_component(ASTRO_KEYWORDS, "; ".join(ASTRO_KEYWORDS))
    assert full == 1.0


def test_topic_component_is_neutral_when_nothing_was_asked():
    value, matched = topic_component([], "anything at all")
    assert value == 0.5 and matched == []


def test_country_component_grades_confirmed_unverified_and_wrong():
    assert country_component("Germany", "Germany") == 1.0
    assert country_component("unverified", "Germany") == 0.4
    assert country_component(None, "Germany") == 0.4
    assert country_component("France", "Germany") == 0.0
    assert country_component("France", None) == 1.0     # nothing asked


# --- 4B: off-field candidates are removed, not merely down-weighted ----------

def test_off_field_candidates_are_gated_out():
    """A productive, senior, correctly-located researcher working on something
    else is the wrong person — that is what "non-related field results" meant.
    Scoring alone could not sink them."""
    assert passes_relevance_gate(
        candidate("radio astronomy; star formation"), ASTRO_KEYWORDS) is True
    assert passes_relevance_gate(
        candidate("medieval poetry; textual criticism"),
        ASTRO_KEYWORDS) is False


def test_the_gate_excludes_nobody_when_no_keywords_were_given():
    assert passes_relevance_gate(candidate("anything"), []) is True
    assert passes_relevance_gate(candidate("anything"), None) is True


def test_the_gate_reads_papers_as_well_as_topics():
    row = candidate("", 5, 2)
    row["representative_papers"] = "A study of the interstellar medium (2024)"
    assert passes_relevance_gate(row, ASTRO_KEYWORDS) is True
