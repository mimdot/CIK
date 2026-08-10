"""Tests for pipeline.run (migration Step 8) — sort, NEW-entry detection,
outputs, and the orchestration runner via injected records. Functions are
also re-exported by the monolith; these exercise the extracted module
directly."""

from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from core.config import build_config
import pipeline.run as RN


def _cfg(tmp_path, **kw):
    cfg = build_config(argparse.Namespace(
        no_config=True, debug=False, phd_only=False, field=None))
    cfg.output_path = os.path.join(str(tmp_path), "out")
    cfg.write_html = kw.get("write_html", False)
    return cfg


def _rec(**kw):
    r = {"title": "PhD in stellar astrophysics", "institution": "MPIfR",
         "country": "Germany", "url": "https://ex.org/j/1",
         "source": "euraxess", "relevance_score": 1.0,
         "deadline": "2026-09-30", "posted_date": "2026-06-01"}
    r.update(kw)
    return r


def test_sort_key_relevance_then_deadline():
    high = _rec(title="a", relevance_score=8.0, deadline="2027-01-01")
    soon = _rec(title="b", relevance_score=5.0, deadline="2026-09-01")
    later = _rec(title="c", relevance_score=5.0, deadline="2026-10-01")
    none = _rec(title="d", relevance_score=5.0, deadline=None)
    got = sorted([later, high, none, soon], key=RN.sort_key)
    assert got[0]["title"] == "a"
    assert [g["title"] for g in got[1:]] == ["b", "c", "d"]


def test_mark_new_first_run_and_second(tmp_path):
    keys, first = RN.load_previous_keys(os.path.join(str(tmp_path), "nope.json"))
    assert first is True and keys == set()
    recs = [_rec(url="https://ex.org/a/1"),
            _rec(title="PhD in cosmology", institution="Leiden",
                 url="https://ex.org/b/2")]
    assert RN.mark_new(recs, keys, first) == 0
    assert all(not r["is_new"] for r in recs)

    # fake previous output -> all keys known except one new URL
    prev_path = os.path.join(str(tmp_path), "prev.json")
    with open(prev_path, "w") as fh:
        json.dump([_rec(url="https://ex.org/a/1")], fh)
    keys, first = RN.load_previous_keys(prev_path)
    assert first is False
    n = RN.mark_new(recs, keys, first)
    assert n == 1
    assert recs[1]["is_new"] is True


def test_write_outputs_json_and_csv(tmp_path):
    cfg = _cfg(tmp_path)
    recs = [_rec(url="https://ex.org/j/1", matched_keywords=["magnetic fields"])]
    RN.write_outputs(recs, cfg)
    assert os.path.exists(cfg.json_path)
    with open(cfg.json_path) as fh:
        assert len(json.load(fh)) == 1
    assert os.path.exists(cfg.csv_path)
    df = pd.read_csv(cfg.csv_path)
    assert len(df) == 1


def test_write_html_embeds_payload(tmp_path):
    cfg = _cfg(tmp_path, write_html=True)
    recs = [_rec(url="https://ex.org/j/1")]
    RN.write_outputs(recs, cfg)
    assert os.path.exists(cfg.html_path)
    with open(cfg.html_path) as fh:
        html = fh.read()
    assert "PhD in stellar astrophysics" in html


def test_run_injected_raw(tmp_path, capsys):
    cfg = _cfg(tmp_path, write_html=False)
    cfg.max_age_days = 365
    raw = [_rec(url="https://ex.org/j/1", deadline="2026-09-30"),
           _rec(url="https://ex.org/j/2", deadline="2020-01-01")]  # expired
    out = RN.run(cfg, injected_raw=raw)
    assert len(out) == 1
    assert out[0]["url"] == "https://ex.org/j/1"
    assert os.path.exists(cfg.json_path)
    captured = capsys.readouterr()
    assert "Total positions" in captured.out
