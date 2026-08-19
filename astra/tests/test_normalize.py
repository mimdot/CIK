"""Country and institution auto-correct (Phase 2D).

Before: a 53-entry hand-written country map — silent on the other ~200
countries, no typo tolerance — and no institution normalisation at all, so
"MIT" and "Massachusetts Institute of Technology" were different employers to
dedupe and grouping.

The brief's acceptance test: "Country/university auto-correct maps a
misspelling and an abbreviation to the canonical form."
"""

from __future__ import annotations

import pytest

from core.iso3166 import COUNTRIES
from core.normalize import (FUZZY_THRESHOLD, country_choices,
                            normalize_country, normalize_institution,
                            suggest_country, suggest_institution)


# --- the dataset --------------------------------------------------------------

def test_the_full_iso3166_list_is_vendored():
    assert len(COUNTRIES) > 240, "the whole standard, not a hand-picked subset"
    codes = {c[0] for c in COUNTRIES}
    assert {"DE", "GB", "US", "IR", "KZ", "FJ", "BT"} <= codes


def test_country_choices_are_offered_for_a_picker():
    choices = country_choices()
    assert len(choices) > 240 and choices == sorted(choices)
    assert "Germany" in choices


# --- THE ACCEPTANCE TEST ------------------------------------------------------

def test_a_misspelling_maps_to_the_canonical_form():
    assert normalize_country("Germny") == "Germany"
    assert normalize_country("Switzerlnd") == "Switzerland"
    assert normalize_country("Untied States") == "United States"
    assert normalize_institution("Massachusets Institute of Technology") == \
        "Massachusetts Institute of Technology"
    assert normalize_institution("Univeristy of Oxford") == "University of Oxford"


def test_an_abbreviation_maps_to_the_canonical_form():
    assert normalize_country("DE") == "Germany"        # alpha-2
    assert normalize_country("DEU") == "Germany"       # alpha-3
    assert normalize_country("UK") == "United Kingdom"
    assert normalize_country("USA") == "United States"
    assert normalize_institution("MIT") == "Massachusetts Institute of Technology"
    assert normalize_institution("Caltech") == "California Institute of Technology"
    assert normalize_institution("ETH Zurich") == \
        "Swiss Federal Institute of Technology Zurich"


# --- countries ----------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("Germany", "Germany"),
    ("  germany  ", "Germany"),
    ("Deutschland", "Germany"),
    ("Holland", "Netherlands"),
    ("Great Britain", "United Kingdom"),
    ("England", "United Kingdom"),
    ("america", "United States"),
    ("Czech Republic", "Czechia"),
    ("Turkey", "Türkiye"),
    ("South Korea", "Korea, Republic of"),
    ("Iran", "Iran, Islamic Republic of"),
    ("Vietnam", "Viet Nam"),
    ("Ivory Coast", "Côte d'Ivoire"),
    # The long tail the 53-entry map never covered:
    ("Kazakhstan", "Kazakhstan"),
    ("Bhutan", "Bhutan"),
    ("Fiji", "Fiji"),
    ("Uruguay", "Uruguay"),
])
def test_countries_resolve(value, expected):
    assert normalize_country(value) == expected


def test_accents_and_punctuation_do_not_matter():
    assert normalize_country("Cote d'Ivoire") == "Côte d'Ivoire"
    assert normalize_country("COTE D IVOIRE") == "Côte d'Ivoire"
    assert normalize_country("Turkiye") == "Türkiye"


def test_a_misspelled_alias_still_resolves():
    """Fuzzy matching runs over aliases too, not just canonical names."""
    assert normalize_country("Nederlnd") == "Netherlands"
    assert normalize_country("Deutschlnd") == "Germany"
    assert normalize_country("Great Britian") == "United Kingdom"


# --- it must not INVENT an answer --------------------------------------------

def test_similar_but_different_countries_are_not_confused():
    """Silently turning Niger into Nigeria is worse than not answering."""
    assert normalize_country("Niger") == "Niger"
    assert normalize_country("Nigeria") == "Nigeria"
    assert normalize_country("Chad") == "Chad"
    assert normalize_country("Chile") == "Chile"
    assert normalize_country("China") == "China"


def test_nonsense_returns_nothing_rather_than_a_guess():
    for value in ("Freedonia", "xyzzy", "zzzz", "", "   ", None):
        assert normalize_country(value) is None


def test_very_short_input_is_not_fuzzy_matched():
    """Two-letter strings are codes; fuzzing them invites nonsense."""
    assert normalize_country("US") == "United States"   # exact code
    assert normalize_country("QQ") is None              # not a code, too short


def test_the_threshold_is_a_real_floor():
    assert 0.8 < FUZZY_THRESHOLD < 1.0


# --- how it resolved, for a "did you mean?" prompt ---------------------------

def test_a_suggestion_reports_how_it_resolved():
    assert suggest_country("Germany").how == "exact"
    assert suggest_country("Germany").is_correction is False
    assert suggest_country("DE").how == "code"
    assert suggest_country("Deutschland").how == "alias"
    assert suggest_country("Germny").how == "fuzzy"
    for value in ("DE", "Deutschland", "Germny"):
        assert suggest_country(value).is_correction is True


def test_a_fuzzy_suggestion_carries_a_confidence():
    hit = suggest_country("Germny")
    assert 0.86 <= hit.score < 1.0
    assert suggest_country("Germany").score == 1.0


# --- institutions -------------------------------------------------------------

def test_institution_abbreviations_resolve():
    for value in ("MIT", "m.i.t.", "M I T"):
        assert normalize_institution(value) == \
            "Massachusetts Institute of Technology"


def test_institutions_from_the_field_profiles_are_known_for_free():
    """The departments: blocks already list hundreds of real institutions."""
    hit = suggest_institution("Leiden University")
    assert hit is not None and "Leiden" in hit.value


def test_an_unknown_institution_is_kept_not_dropped():
    """The world has more universities than any list — never lose an employer."""
    assert normalize_institution("Some Tiny College Nobody Lists") == \
        "Some Tiny College Nobody Lists"
    assert normalize_institution("  Spaced   Out  University ") == \
        "Spaced Out University"
    assert normalize_institution(None) is None


# --- applied to SCRAPED data, before dedupe and grouping ---------------------

def test_scraped_countries_go_through_the_full_table():
    from core.utils import canonical_country
    assert canonical_country("Kazakhstan") == "Kazakhstan"
    assert canonical_country("KZ") == "Kazakhstan"
    assert canonical_country("Germny") == "Germany"


def test_the_filter_normalises_institutions_so_they_group_as_one():
    import argparse

    from core.config import build_config
    from core.records import make_record
    from pipeline.filter import filter_records

    cfg = build_config(argparse.Namespace(field="astronomy", no_config=True))
    records = [
        make_record(title="PhD in Radio Astronomy", url=f"https://x/{i}",
                    institution=name,
                    short_description="radio astronomy interstellar medium",
                    source="t")
        for i, name in enumerate(["MIT", "m.i.t.",
                                  "Massachusetts Institute of Technology"])
    ]
    kept = filter_records(records, cfg)
    assert len(kept) == 3
    assert {r["institution"] for r in kept} == {
        "Massachusetts Institute of Technology"}, \
        "three spellings must group as ONE employer"


def test_normalisation_never_breaks_a_record():
    """A crawl must survive whatever a job board puts in these fields."""
    for value in ("", "   ", "123", "🔬", "<script>", "a" * 500):
        normalize_country(value)
        normalize_institution(value)
