#!/usr/bin/env python3
"""Tests for Sprint 03 Track C: CLI wiring for the profile/DB features.

C1 --build-profile (LLM extraction -> DB), C2 --seed-db, C3 --run with an
active profile scores every opportunity, C4 --show-profile. All offline:
the LLM is a stub and the DB is a temp SQLite file. litellm is never touched.
"""

from __future__ import annotations

import argparse
import json

import pytest

import phd_aggregator as P
from cli.commands import (build_profile_cmd, db_available, load_active_profile,
                          seed_db_cmd, show_profile_cmd)
from core.config import build_config
from core.profile_schema import UserProfile

STUB_PROFILE_JSON = {
    "domain": "astronomy",
    "subfield": "interstellar medium",
    "methods": ["radio interferometry", "MHD simulation"],
    "tools": ["LOFAR", "Python"],
    "skills": ["dust polarization"],
    "experience_level": "phd_student",
    "target_roles": ["postdoc"],
    "countries_preferred": ["Germany"],
    "funding_requirement": None,
    "constraints": [],
    "confidence": 0.85,
    "raw_text": "some cv text",
}


class StubLLM:
    """A fake LLMRouter backend: returns the profile JSON whatever the prompt."""

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        return json.dumps(STUB_PROFILE_JSON)


def _db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path}/phd_data.db"


# ---------------------------------------------------------------------------
# parse_args plumbing
# ---------------------------------------------------------------------------
def test_parse_args_track_c_defaults():
    a = P.parse_args([])
    assert a.build_profile is None
    assert a.seed_db is None
    assert a.show_profile is False
    assert a.db is None


def test_parse_args_track_c_flags():
    a = P.parse_args(["--build-profile", "I am a student of astronomy",
                      "--seed-db", "phd_positions.json",
                      "--show-profile", "--db", "sqlite:///x.db"])
    assert a.build_profile == "I am a student of astronomy"
    assert a.seed_db == "phd_positions.json"
    assert a.show_profile is True
    assert a.db == "sqlite:///x.db"


def test_parse_args_build_profile_requires_value():
    with pytest.raises(SystemExit):
        P.parse_args(["--build-profile"])


# ---------------------------------------------------------------------------
# C1 — --build-profile
# ---------------------------------------------------------------------------
def test_build_profile_cmd_saves_active_profile(tmp_path, capsys):
    url = _db_url(tmp_path)
    rc = build_profile_cmd("I am a PhD student in astronomy.", db_url=url,
                           llm=StubLLM())
    assert rc == 0
    out = capsys.readouterr().out
    assert '"domain": "astronomy"' in out
    prof = load_active_profile(url)
    assert prof is not None
    assert prof.domain == "astronomy"
    assert prof.countries_preferred == ["Germany"]


def test_build_profile_cmd_replaces_active_profile(tmp_path):
    url = _db_url(tmp_path)
    assert build_profile_cmd("v1", db_url=url, llm=StubLLM()) == 0
    first = load_active_profile(url)
    assert build_profile_cmd("v2", db_url=url, llm=StubLLM()) == 0
    second = load_active_profile(url)
    assert second is not None and first is not None
    assert second.domain == "astronomy"      # the new profile is active


def test_build_profile_cmd_failure_returns_one(tmp_path, capsys):
    class FailingLLM:
        def complete(self, prompt, schema=None):      # noqa: A002
            return "not json at all"

    url = _db_url(tmp_path)
    rc = build_profile_cmd("some text", db_url=url, llm=FailingLLM())
    assert rc == 1
    assert load_active_profile(url) is None


def test_main_routes_build_profile(tmp_path, monkeypatch, capsys):
    url = _db_url(tmp_path)
    captured = {}

    def fake_build(text, db_url=None):
        captured["text"] = text
        captured["db_url"] = db_url
        return 0

    monkeypatch.setattr(P, "build_profile_cmd", fake_build)
    rc = P.main(["--db", url, "--build-profile", "hello astronomy"])
    assert rc == 0
    assert captured["text"] == "hello astronomy"
    assert captured["db_url"] == url


# ---------------------------------------------------------------------------
# C2 — --seed-db
# ---------------------------------------------------------------------------
def _write_seed_json(tmp_path, records=None):
    seed = records or [
        {"title": "PhD in radio astronomy", "institution": "MPIfR",
         "country": "Germany", "deadline": "2026-09-30", "url": "https://e/j1",
         "source": "euraxess", "relevance_score": 8.2,
         "matched_keywords": ["radio astronomy"],
         "short_description": "Doctoral project on radio astronomy.",
         "position_type": "phd", "is_new": True},
        {"title": "PhD in cosmology", "institution": "Leiden",
         "country": "Netherlands", "url": "https://e/j2", "source": "findaphd",
         "relevance_score": 7.5, "matched_keywords": [],
         "short_description": "Observational cosmology.",
         "position_type": "phd", "is_new": False},
    ]
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(seed), encoding="utf-8")
    return str(path)


def test_seed_db_cmd_counts_records(tmp_path, capsys):
    url = _db_url(tmp_path)
    seed = _write_seed_json(tmp_path)
    rc = seed_db_cmd(seed, db_url=url)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Seeded 2 record(s)" in out
    assert "total opportunities in DB: 2" in out


def test_seed_db_is_idempotent(tmp_path):
    url = _db_url(tmp_path)
    seed = _write_seed_json(tmp_path)
    seed_db_cmd(seed, db_url=url)
    seed_db_cmd(seed, db_url=url)
    from db.init import count_opportunities
    from db.init import init_db
    from sqlalchemy.orm import Session
    with Session(init_db(url)) as s:
        assert count_opportunities(s) == 2     # upsert, not duplicated


def test_seed_db_missing_file_counts_zero(tmp_path, capsys):
    url = _db_url(tmp_path)
    rc = seed_db_cmd(str(tmp_path / "nope.json"), db_url=url)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Seeded 0 record(s)" in out


# ---------------------------------------------------------------------------
# C3 — --run with an active profile
# ---------------------------------------------------------------------------
def test_load_active_profile_none_when_no_db(tmp_path):
    assert load_active_profile(_db_url(tmp_path)) is None


def test_db_available_requires_existing_file(tmp_path):
    url = _db_url(tmp_path)
    assert db_available(url) is False
    (tmp_path / "phd_data.db").write_text("", encoding="utf-8")
    assert db_available(url) is True


def test_main_run_no_fetch_scores_with_profile(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    assert build_profile_cmd("CV text", db_url=url, llm=StubLLM()) == 0

    output_base = str(tmp_path / "out")
    json_path = output_base + ".json"
    recs = [
        {"title": "PhD in interstellar medium radio astronomy",
         "institution": "MPIfR", "country": "Germany", "url": "https://e/j1",
         "source": "euraxess", "relevance_score": 8.0,
         "matched_keywords": ["ISM"], "short_description":
             "Radio interferometry with LOFAR.",
         "position_type": "phd", "is_new": False},
        {"title": "PhD in medieval history", "institution": "Ox",
         "country": "UK", "url": "https://e/j2", "source": "findaphd",
         "relevance_score": 6.0, "matched_keywords": [],
         "short_description": "Parchment analysis.", "position_type": "phd",
         "is_new": False},
    ]
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(recs, fh)

    scored = {}

    def fake_apply(records, profile, cfg):
        scored["records"] = records
        scored["profile"] = profile
        return records

    monkeypatch.setattr(P, "apply_profile_matching", fake_apply)
    rc = P.main(["--db", url, "--no-config", "--no-fetch",
                 "--output", output_base, "--no-html"])
    assert rc == 0
    assert scored["records"] is not None and len(scored["records"]) == 2
    assert scored["profile"] is not None
    assert scored["profile"].domain == "astronomy"


def test_main_run_without_db_has_no_match_fields(tmp_path):
    output_base = str(tmp_path / "out")
    json_path = output_base + ".json"
    recs = [{"title": "PhD in x", "url": "https://e/j1", "source": "aas",
             "short_description": "", "position_type": "phd", "is_new": False}]
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(recs, fh)
    rc = P.main(["--db", str(tmp_path / "missing.db"), "--no-config",
                 "--no-fetch", "--output", output_base, "--no-html"])
    assert rc == 0
    with open(json_path, "r", encoding="utf-8") as fh:
        out_recs = json.load(fh)
    assert "match_score" not in out_recs[0]


def test_main_run_passes_active_profile_to_run(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    assert build_profile_cmd("CV text", db_url=url, llm=StubLLM()) == 0
    seen = {}

    def fake_run(cfg, only_sources=None, limit_per_source=None,
                 injected_raw=None, profile=None):
        seen["profile"] = profile
        return []

    monkeypatch.setattr(P, "run", fake_run)
    rc = P.main(["--db", url, "--no-config", "--source", "eso"])
    assert rc == 0
    assert seen["profile"] is not None
    assert seen["profile"].domain == "astronomy"


def test_main_run_no_fetch_persists_scored_output(tmp_path):
    url = _db_url(tmp_path)
    assert build_profile_cmd("CV text", db_url=url, llm=StubLLM()) == 0

    output_base = str(tmp_path / "out")
    recs = [{"title": "PhD in interstellar medium radio astronomy",
             "institution": "MPIfR", "country": "Germany", "url": "https://e/j1",
             "source": "euraxess", "relevance_score": 8.0,
             "matched_keywords": ["ISM"],
             "short_description": "Radio interferometry with LOFAR.",
             "position_type": "phd", "is_new": False}]
    with open(output_base + ".json", "w", encoding="utf-8") as fh:
        json.dump(recs, fh)

    rc = P.main(["--db", url, "--no-config", "--no-fetch",
                 "--output", output_base, "--no-html"])
    assert rc == 0
    with open(output_base + ".json", "r", encoding="utf-8") as fh:
        scored = json.load(fh)
    assert scored[0]["match_score"] > 0.8    # strong topic + location, partial methods
    assert "match_explanation" in scored[0]
    import os
    assert os.path.exists(output_base + ".csv")


def test_main_run_passes_none_profile_without_db(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cfg, only_sources=None, limit_per_source=None,
                 injected_raw=None, profile=None):
        seen["profile"] = profile
        return []

    monkeypatch.setattr(P, "run", fake_run)
    rc = P.main(["--db", str(tmp_path / "missing.db"), "--no-config",
                 "--source", "eso"])
    assert rc == 0
    assert seen["profile"] is None


# ---------------------------------------------------------------------------
# C4 — --show-profile
# ---------------------------------------------------------------------------
def test_show_profile_cmd_empty_returns_one(tmp_path, capsys):
    rc = show_profile_cmd(db_url=_db_url(tmp_path))
    assert rc == 1
    out = capsys.readouterr().out
    assert "No active profile" in out


def test_show_profile_cmd_prints_profile(tmp_path, capsys):
    url = _db_url(tmp_path)
    build_profile_cmd("cv", db_url=url, llm=StubLLM())
    rc = show_profile_cmd(db_url=url)
    assert rc == 0
    out = capsys.readouterr().out
    assert '"domain": "astronomy"' in out
    assert '"radio interferometry"' in out


def test_main_show_profile_roundtrip(tmp_path, capsys):
    url = _db_url(tmp_path)
    build_profile_cmd("cv", db_url=url, llm=StubLLM())
    rc = P.main(["--db", url, "--show-profile"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "astronomy" in out
