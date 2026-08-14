"""Subfield focus + per-field supervisor routing (Phase 1B/1C).

Two behaviours:

* Subfields NARROW a run without throwing results away: their keywords join
  ``context_terms``, which boost a post's score but can never qualify one on
  their own. Job ads are short and often never name their subfield, so a hard
  filter would discard good positions.
* NASA ADS is an astronomy database. It must serve astronomy and physics and
  nothing else — in particular it must not become the default backend for a
  brand-new field profile just because SUPERVISOR_ADS_DB defaults to
  "astronomy".
"""

from __future__ import annotations

import argparse

import pytest

from core.config import apply_subfield_focus, build_config
from supervisors.chain import _supervisor_chain


def _cfg(field=None, **kw):
    return build_config(argparse.Namespace(field=field, no_config=True, **kw))


# --- subfield focus ----------------------------------------------------------

def test_subfield_keywords_become_boost_terms_not_gates():
    cfg = _cfg("chemistry")
    before_context = len(cfg.context_terms)
    before_anchors = list(cfg.core_anchors)

    matched = apply_subfield_focus(cfg, ["organic"])

    assert matched == ["organic"]
    assert len(cfg.context_terms) > before_context, "keywords must boost"
    # Crucially: the qualifying gate is untouched, so a chemistry post that
    # never says "organic" can still surface.
    assert cfg.core_anchors == before_anchors


def test_multiple_subfields_all_contribute():
    cfg = _cfg("chemistry")
    baseline = len(cfg.context_terms)
    matched = apply_subfield_focus(cfg, ["organic", "catalysis", "analytical"])
    assert matched == ["organic", "catalysis", "analytical"]
    assert len(cfg.context_terms) > baseline + 10


def test_unknown_subfield_is_reported_and_skipped(caplog):
    """Never silently narrow a search to nothing on a typo."""
    cfg = _cfg("chemistry")
    with caplog.at_level("WARNING"):
        matched = apply_subfield_focus(cfg, ["organic", "not_a_subfield"])
    assert matched == ["organic"]
    assert "not_a_subfield" in caplog.text


def test_subfield_selection_is_recorded_on_the_config():
    cfg = _cfg("chemistry")
    apply_subfield_focus(cfg, ["organic"])
    assert cfg.selected_subfields == ["organic"]


def test_no_subfields_leaves_the_taxonomy_alone():
    cfg = _cfg("chemistry")
    before = list(cfg.context_terms)
    apply_subfield_focus(cfg, [])
    assert cfg.context_terms == before


def test_build_config_applies_subfields_from_args():
    cfg = build_config(argparse.Namespace(field="chemistry", no_config=True,
                                          subfields=["organic"]))
    assert cfg.selected_subfields == ["organic"]
    assert any("total synthesis" in t for t in cfg.context_terms)


def test_boost_terms_are_deduplicated():
    cfg = _cfg("chemistry")
    apply_subfield_focus(cfg, ["organic"])
    once = len(cfg.context_terms)
    apply_subfield_focus(cfg, ["organic"])
    assert len(cfg.context_terms) == once


# --- supervisor routing ------------------------------------------------------

@pytest.mark.parametrize("field", ["astronomy", "physics", "condensed_matter"])
def test_ads_indexed_fields_use_ads_when_a_token_exists(field):
    assert _supervisor_chain(_cfg(field), token=True)[0] == "ads"


@pytest.mark.parametrize("field", ["chemistry", "biology", "computer_science",
                                   "economics", "mathematics", "geology"])
def test_other_fields_never_route_to_ads(field):
    """ADS indexes astronomy + physics. Everything else goes to OpenAlex."""
    assert "ads" not in _supervisor_chain(_cfg(field), token=True)
    assert "ads" not in _supervisor_chain(_cfg(field), token=False)


def test_new_profile_without_supervisor_keys_does_not_default_to_ads():
    """The F6 regression: SUPERVISOR_ADS_DB defaults to 'astronomy', so a
    profile that never mentions it used to route to an astronomy database as
    soon as an ADS token was present.

    Models exactly what apply_field_profile() leaves behind for a YAML with no
    supervisor_* keys (as fields/template.yaml ships): the inherited default
    value, and explicit=False.
    """
    cfg = _cfg()
    cfg.field_profile = "marine_biology"       # a field ADS does not index
    cfg.supervisor_ads_db = "astronomy"        # inherited, not chosen
    cfg.supervisor_ads_db_explicit = False
    cfg.supervisor_source = "auto"
    assert _supervisor_chain(cfg, token=True) == ["openalex", "arxiv"]


def test_template_profile_ships_without_supervisor_keys():
    """Guards the premise of the test above: template.yaml must not pin an ADS
    collection, or every field copied from it inherits astronomy routing."""
    from core.config import load_field_profile
    template = load_field_profile("template") or {}
    assert "supervisor_ads_db" not in template
    assert "supervisor_source" not in template


def test_profile_that_names_an_ads_collection_is_believed():
    """An explicit supervisor_ads_db is a deliberate statement — honour it."""
    cfg = _cfg("astronomy")
    assert cfg.supervisor_ads_db_explicit is True
    assert _supervisor_chain(cfg, token=True) == ["ads", "openalex"]


def test_explicit_ads_request_from_an_unindexed_field_is_redirected(caplog):
    cfg = _cfg("chemistry")
    cfg.supervisor_source = "ads"
    with caplog.at_level("WARNING"):
        chain = _supervisor_chain(cfg, token=True)
    assert chain == ["openalex", "arxiv"]
    assert "astronomy and physics only" in caplog.text


def test_openalex_is_the_tokenless_fallback_everywhere():
    for field in ("astronomy", "chemistry", "economics"):
        assert _supervisor_chain(_cfg(field), token=False)[0] == "openalex"
