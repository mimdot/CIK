#!/usr/bin/env python3
"""Offline tests for core/taxonomy.py (migration Step 3 — the HIGH-RISK step).

Scoring, the relevance gate, and the position-type classifier are pinned here
so any silent divergence during extraction is caught immediately. Also checks
the back-compat re-export surface through the phd_aggregator monolith.

Run:  python -m pytest tests/test_taxonomy.py -q
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phd_aggregator as P
from core.config import build_config
from core.taxonomy import compile_taxonomy, score_relevance


def _make_cfg(**overrides):
    base = dict(no_config=True, debug=False, phd_only=False, field=None)
    base.update(overrides)
    ns = argparse.Namespace(**base)
    cfg = build_config(ns)
    compile_taxonomy(cfg)
    return cfg


def _score(cfg, title, desc=""):
    return score_relevance(title, desc, cfg)  # (score, core, ctx, neg)


# ---------------------------------------------------------------- scoring
def test_score_relevance_core_in_title_high_score():
    cfg = _make_cfg()
    s, core, ctx, neg = _score(cfg, "Astrophysics PhD position", "")
    w = cfg.weights
    assert s >= w["core_title"]
    assert "astrophysic" in core
    assert core and ctx == [] and neg == []


def test_score_relevance_core_in_desc_lower_score():
    cfg = _make_cfg()
    s_title, _, _, _ = _score(cfg, "Astrophysics PhD position", "")
    s_desc, core, ctx, _ = _score(cfg, "Position", "research in astrophysics")
    assert s_desc < s_title
    assert core and "astrophysic" in core


def test_score_relevance_context_only_no_anchor():
    cfg = _make_cfg()
    s, core, ctx, _ = _score(cfg, "Theoretical position in magnetism", "")
    assert not core, "context terms alone must not form a core anchor"
    assert ctx, "expected a context term to match"
    assert P.is_relevant(s, core, cfg) is False


def test_score_relevance_negative_deducted():
    cfg = _make_cfg()
    s, core, _, neg = _score(cfg, "Quantum computing position", "noise, new paths")
    assert neg, "expected a negative term to match"
    assert not core
    assert s < 0.0


def test_score_relevance_negative_skipped_when_title_anchor():
    cfg = _make_cfg()
    # A genuine crossover: core anchor in the TITLE plus a negative term ->
    # the negative is detected but NOT deducted.
    s, core, _, neg = _score(cfg, "Astrophysics of quantum information",
                             "research opportunities")
    assert core, "expected a core anchor in the title"
    assert neg, "negative term detected alongside the title anchor"
    assert s >= cfg.weights["core_title"] * len(core), \
        "negatives must be ignored when a core anchor is in the title"


# ---------------------------------------------------------------- relevance gate
def test_is_relevant_requires_anchor():
    cfg = _make_cfg()
    assert P.is_relevant(9.0, [], cfg) is False


def test_is_relevant_requires_threshold():
    cfg = _make_cfg()
    assert P.is_relevant(1.0, ["astrophysic"], cfg) is False


def test_require_title_anchor_blocks_desc_only():
    cfg = _make_cfg()
    cfg.require_title_anchor = True
    x, core, _, _ = _score(cfg, "Position", "research in astrophysics themes")
    assert core
    assert P.is_relevant(x, core, cfg, title_anchors=[]) is False
    assert P.is_relevant(x, core, cfg, title_anchors=core) is True


# ---------------------------------------------------------------- classifier
def test_classify_position_type_phd():
    assert P.classify_position_type("PhD in Astrophysics", "") == "phd"
    assert P.classify_position_type("Doctoral position in astronomy", "") == "phd"
    assert P.classify_position_type("Graduate student fellowship", "") == "phd"


def test_classify_position_type_postdoc_not_leaked():
    # The historical bug: "Post Doctoral" used to leak into phd via 'doctoral'.
    assert P.classify_position_type("Post Doctoral Research Associate", "") == "postdoc"
    assert P.classify_position_type("Postdoctoral Fellow in Astronomy", "") == "postdoc"


def test_classify_position_type_unknown():
    assert P.classify_position_type("Completely unrelated listing", "") == "unknown"
    assert P.classify_position_type(None, "") == "unknown"


def test_classify_position_type_desc_with_phd_requirement_noise():
    # A postdoc ad saying "must hold a PhD" must not be re-labeled phd.
    assert P.classify_position_type(
        "Research Fellow in Astrobiology",
        "Candidates must hold a PhD in a related field.") == "postdoc"


# ---------------------------------------------------------------- geo gate
def test_country_allowed_smoke():
    cfg = _make_cfg()
    cfg.countries = ["Germany"]
    cfg.keep_ambiguous = False
    assert cfg.geo_filter_active is True
    assert P.country_allowed("Germany", cfg) == (True, False)
    assert P.country_allowed("Japan", cfg) == (False, False)
    assert P.country_allowed(None, cfg) == (False, False)


# ---------------------------------------------------------------- back-compat
def test_backcompat_names_reachable_from_monolith():
    for name in ("score_relevance", "is_relevant", "classify_position_type",
                 "country_allowed", "compile_taxonomy"):
        assert callable(getattr(P, name)), name
    assert P.compile_taxonomy is compile_taxonomy