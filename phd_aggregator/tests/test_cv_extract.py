"""Deterministic, token-free CV analysis (Phase 3B).

The reported bug was a bare "Could not extract profile from text". Root cause:
``core.profile.extract_profile`` calls an LLM, and with no API key configured
it returns None — so describing your own research interests depended on a paid
third-party service, and its absence produced a dead end with no explanation.

This extractor matches the CV against the vocabulary already shipped in
fields/*.yaml. It needs no key, cannot fail wholesale, and every term it
returns is one the relevance engine actually scores against.
"""

from __future__ import annotations

import pytest

from core.cv_extract import MIN_TEXT_CHARS, extract_from_text


CHEMISTRY_CV = """Dr Amina El-Sayed
Department of Chemistry, ETH Zurich, Switzerland

RESEARCH INTERESTS
Asymmetric organocatalysis and total synthesis of natural products.
Expertise in flow chemistry and synthetic methodology.

EDUCATION
PhD in Organic Chemistry, ETH Zurich, 2021
MSc Chemistry, Cairo University, 2017

SKILLS
NMR spectroscopy, HPLC, mass spectrometry, Python
"""

CS_CV = """Bjorn Sigurdsson
Postdoctoral Researcher | KTH Royal Institute of Technology, Sweden
RESEARCH  machine learning, deep learning, computer vision, natural language
processing. Published at NeurIPS and ICML.
TOOLS  Python, PyTorch, TensorFlow, Linux, git
"""

ASTRO_CV = """Prof. Wei Zhang, National Astronomical Observatories, China
Research: radio astronomy, interstellar medium, star formation, ALMA
observations of molecular clouds. Tools: Python, CASA.
"""

TWO_COLUMN_CV = """Maria  Fernandez-Lopez          EDUCATION
Universidad de Barcelona        PhD Biology, 2020
Spain                           MSc Genetics, 2016

RESEARCH                        SKILLS
molecular biology, genomics     PCR, cell culture, sequencing
gene expression, CRISPR         Python, R language
"""


# --- it recognises real CVs across fields and layouts ------------------------

def test_chemistry_cv_is_recognised():
    r = extract_from_text(CHEMISTRY_CV)
    assert r.field == "chemistry"
    assert "organic" in r.subfields
    assert any("organocatalys" in k for k in r.keywords)
    assert r.experience_level == "phd"
    assert "Switzerland" in r.countries
    assert r.found_anything and r.reason is None


def test_computer_science_cv_is_recognised():
    r = extract_from_text(CS_CV)
    assert r.field == "computer_science"
    assert "machine learning" in r.keywords
    assert r.experience_level == "postdoc"
    assert "Sweden" in r.countries
    assert "pytorch" in r.tools


def test_astronomy_cv_is_recognised():
    r = extract_from_text(ASTRO_CV)
    assert r.field == "astronomy"
    assert "ism" in r.subfields
    assert r.experience_level == "professor"      # "Prof." in the header
    assert "China" in r.countries


def test_two_column_layout_with_a_non_english_name():
    """Column layouts arrive as ragged text; matching must not depend on
    structure, and a non-ASCII name must not break anything."""
    r = extract_from_text(TWO_COLUMN_CV)
    assert r.field == "biology"
    assert r.keywords, "should still find vocabulary in ragged text"
    assert "Spain" in r.countries
    assert "pcr" in r.tools


def test_a_field_hint_scopes_the_scan():
    """When the user has already chosen a field, believe them."""
    r = extract_from_text(CHEMISTRY_CV, field_hint="biology")
    assert r.field == "biology"


# --- it never fails wholesale, and always says WHY ---------------------------

@pytest.mark.parametrize("text,reason", [
    ("", "empty_text"),
    ("Hi there", "too_short"),
    ("asdf qwerty zxcv " * 8, "no_field_match"),
])
def test_unrecognised_input_reports_a_specific_reason(text, reason):
    r = extract_from_text(text)
    assert r.reason == reason
    assert r.notes, "a reason must come with a sentence the UI can show"
    assert r.found_anything is False
    # Crucially: it returned a result rather than raising or returning None.
    assert r.to_dict()["keywords"] == []


def test_it_never_raises_on_hostile_input():
    for text in ("\x00\x01\x02", "((((", "a" * (MIN_TEXT_CHARS + 1),
                 "🔬" * 100, "<script>alert(1)</script>" * 5):
        assert extract_from_text(text) is not None


def test_very_long_text_is_truncated_not_rejected():
    r = extract_from_text(CHEMISTRY_CV + ("filler word " * 40_000))
    assert r.field == "chemistry"
    assert any("only the first part" in n.lower() for n in r.notes)


def test_result_is_json_serialisable():
    import json
    json.dumps(extract_from_text(CHEMISTRY_CV).to_dict())


# --- the terms it returns are the ones the engine understands ----------------

def test_extracted_keywords_come_from_the_shipped_vocabulary():
    """Not free text: every keyword must exist in the field profile, so it
    cannot silently fail to match the way a guessed term could."""
    from core.config import load_field_profile
    r = extract_from_text(CHEMISTRY_CV)
    profile = load_field_profile("chemistry") or {}
    vocabulary = set(profile.get("core_anchors") or [])
    for entry in (profile.get("subfields") or {}).values():
        vocabulary.update(entry.get("keywords") or [])
    assert r.keywords, "sanity: the fixture should match something"
    assert set(r.keywords) <= vocabulary


def test_field_scores_are_reported_so_a_guess_can_be_second_guessed():
    r = extract_from_text(ASTRO_CV)
    assert r.field_scores.get("astronomy", 0) > 0
    assert r.field == max(r.field_scores, key=r.field_scores.get)


# --- countries -----------------------------------------------------------------

def test_lowercase_words_are_not_mistaken_for_countries():
    """'turkey' in a sentence is a bird; only capitalised tokens count."""
    r = extract_from_text(
        "I study the chemistry of turkey and chile peppers in depth, with "
        "organic chemistry methods and total synthesis of natural products.")
    assert "Turkey" not in r.countries and "Chile" not in r.countries
