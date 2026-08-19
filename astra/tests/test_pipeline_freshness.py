"""Tests for pipeline.freshness (migration Step 7, part 1) — state
persistence and the freshness layer. Functions are also re-exported by the
monolith; these tests exercise the extracted module directly."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os

from core.config import build_config
import pipeline.freshness as FR


def _cfg(**kwargs):
    base = dict(no_config=True, debug=False, phd_only=False, field=None)
    base.update(kwargs)
    return build_config(argparse.Namespace(**base))


def _rec(**kw):
    r = {"title": "PhD in X", "institution": "Inst", "url": "https://x.org/1",
         "source": "test", "relevance_score": 1.0}
    r.update(kw)
    return r


def test_freshness_priority_and_aging():
    cfg = _cfg()
    cfg.max_age_days = 365
    state = {"urls": {}}
    today = _dt.date(2026, 8, 2)

    r_old = _rec(title="PhD in stellar astrophysics", url="https://ex.org/f/old",
                 posted_date=(today - _dt.timedelta(days=540)).isoformat())
    r_old_dl = _rec(title="PhD in stellar astrophysics", url="https://ex.org/f/olddl",
                    posted_date=(today - _dt.timedelta(days=540)).isoformat(),
                    deadline=(today + _dt.timedelta(days=30)).isoformat())
    r_undated = _rec(title="PhD in stellar astrophysics", url="https://ex.org/f/undated")
    r_month = _rec(title="PhD in stellar astrophysics", url="https://ex.org/f/new",
                   posted_date=(today - _dt.timedelta(days=10)).isoformat())

    kept = FR.apply_freshness([r_old, r_old_dl, r_undated, r_month], cfg, state,
                              today=today)
    urls = {r["url"] for r in kept}
    assert "https://ex.org/f/old" not in urls          # stale, no deadline
    assert "https://ex.org/f/olddl" in urls            # future deadline keeps
    assert "https://ex.org/f/undated" in urls          # kept on first discovery
    assert "https://ex.org/f/new" in urls
    undated = next(r for r in kept if r["url"].endswith("/undated"))
    assert undated["freshness"] == "undated_new"

    later = today + _dt.timedelta(days=401)
    kept2 = FR.apply_freshness([_rec(title="PhD in stellar astrophysics",
                                    url="https://ex.org/f/undated")],
                              cfg, state, today=later)
    assert not kept2


def test_load_state_defaults_and_roundtrip(tmp_path):
    cfg = _cfg()
    cfg.state_path = os.path.join(str(tmp_path), "state.json")
    state = FR.load_state(cfg)
    assert state == {"version": 1, "urls": {}, "seed_domains": {}}
    state["urls"]["k"] = {"first_seen": "2026-01-01", "last_seen": "2026-01-02"}
    FR.save_state(state, cfg, today=_dt.date(2026, 8, 1))
    loaded = FR.load_state(cfg)
    assert loaded["urls"]["k"] == state["urls"]["k"]
    assert not os.path.exists(cfg.state_path + ".tmp")
    with open(cfg.state_path) as fh:
        assert isinstance(json.load(fh), dict)


def test_save_state_prunes_stale(tmp_path):
    cfg = _cfg()
    cfg.max_age_days = 30
    cfg.state_path = os.path.join(str(tmp_path), "state.json")
    state = {"version": 1,
             "urls": {"old": {"first_seen": "2024-01-01",
                              "last_seen": "2024-02-01"},
                      "new": {"first_seen": "2026-07-01",
                              "last_seen": "2026-07-02"}},
             "seed_domains": {}}
    FR.save_state(state, cfg, today=_dt.date(2026, 8, 1))
    urls = FR.load_state(cfg)["urls"]
    assert "old" not in urls
    assert "new" in urls
