"""Tests for pipeline.filter and pipeline.dedupe (migration Step 7, part 2).
Functions are also re-exported by the monolith; these exercise the extracted
modules directly."""

from __future__ import annotations

import argparse

from core.config import build_config
import pipeline.dedupe as DD
import pipeline.filter as FT


def _cfg(**kwargs):
    base = dict(no_config=True, debug=False, phd_only=False, field=None)
    base.update(kwargs)
    return build_config(argparse.Namespace(**base))


def _rec(**kw):
    r = {"title": "PhD in stellar astrophysics", "institution": "MPIfR",
         "country": "Germany", "url": "https://ex.org/j/1",
         "source": "euraxess"}
    r.update(kw)
    return r


# ---------------------------------------------------------------------------
# filter_records
# ---------------------------------------------------------------------------
def test_filter_seed_bypass_gate():
    cfg = _cfg()
    cfg.seed_bypass_gate = True
    cfg.wanted_types = {"phd"}
    seed = _rec(title="PhD in stellar astrophysics",
                url="https://ex.org/j/seed", _seed=True)
    kept = FT.filter_records([seed], cfg)
    assert len(kept) == 1
    assert kept[0]["_seed"] is True


def test_filter_drops_irrelevant():
    cfg = _cfg()
    r = _rec(title="Undergraduate summer internship in marketing",
             description="No astronomy here at all.")
    kept = FT.filter_records([r], cfg)
    assert len(kept) == 0


def test_filter_keeps_relevant_phd():
    cfg = _cfg()
    r = _rec(title="PhD position in radio astronomy")
    kept = FT.filter_records([r], cfg)
    assert len(kept) == 1
    assert kept[0]["relevance_score"] > 0


# ---------------------------------------------------------------------------
# dedupe_records / _merge_into
# ---------------------------------------------------------------------------
def test_dedupe_merges_by_url():
    a = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
             url="https://a.org/1", source="esa")
    b = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
             url="https://a.org/1", source="euraxess")
    out = DD.dedupe_records([a, b])
    assert len(out) == 1
    assert "esa" in out[0]["source"] and "euraxess" in out[0]["source"]


def test_dedupe_merges_same_title_different_boards():
    a = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
             url="https://a.org/1")
    b = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
             url="https://b.org/2")
    assert len(DD.dedupe_records([a, b])) == 1


def test_dedupe_keeps_distinct_jobs():
    a = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
             url="https://a.org/1")
    b = _rec(title="PhD in cosmology", institution="MPIfR",
             url="https://a.org/2")
    assert len(DD.dedupe_records([a, b])) == 2


def test_merge_into_fills_missing_and_takes_best():
    base = _rec(title="PhD in stellar astrophysics", url="https://a.org/1",
                source="esa", position_type="unknown")
    dup = _rec(title="PhD in stellar astrophysics", url="https://a.org/1",
               source="euraxess", position_type="phd",
               relevance_score=0.8)
    DD._merge_into(base, dup)
    assert base["position_type"] == "phd"
    assert base["relevance_score"] == 0.8
    assert set(base["source"].split("; ")) == {"esa", "euraxess"}
