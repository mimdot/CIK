#!/usr/bin/env python3
"""Tests for the CLI layer of the slimmed monolith (migration Step 11).

parse_args() argument handling, plus the cheap, offline main() entry points
(--list-sources, --list-fields, --self-test, --new-field validation) invoked
through the real module. No network, no scraping.
"""

from __future__ import annotations

import argparse
import io

import pytest

import astra as P


# ---------------------------------------------------------------------------
# parse_args — flag plumbing
# ---------------------------------------------------------------------------
def test_parse_args_defaults():
    a = P.parse_args([])
    assert a.list_sources is False
    assert a.list_fields is False
    assert a.self_test is False
    assert a.find_supervisors is False
    assert a.source is None
    assert a.country is None
    assert a.field is None
    assert a.output is None
    assert a.no_config is False
    assert a.no_fetch is False
    assert a.extras is False


def test_parse_args_boolean_flags():
    a = P.parse_args(["--self-test", "--list-sources", "--find-supervisors",
                      "--extras", "--no-config", "--debug"])
    assert a.self_test and a.list_sources and a.find_supervisors
    assert a.extras and a.no_config and a.debug


def test_parse_args_repeatable_country_and_source():
    a = P.parse_args(["--country", "*", "--country", "Germany",
                      "--source", "eso", "--source", "euraxess"])
    assert a.country == ["*", "Germany"]
    assert a.source == ["eso", "euraxess"]


def test_parse_args_numeric_overrides():
    a = P.parse_args(["--threshold", "3.5", "--max-age-days", "60",
                      "--years-back", "7", "--limit-per-source", "10"])
    assert a.threshold == 3.5
    assert a.max_age_days == 60
    assert a.years_back == 7
    assert a.limit_per_source == 10


def test_parse_args_supervisor_source_choice():
    a = P.parse_args(["--supervisor-source", "openalex"])
    assert a.supervisor_source == "openalex"
    with pytest.raises(SystemExit):
        P.parse_args(["--supervisor-source", "bogus"])


def test_parse_args_output_and_field():
    a = P.parse_args(["--output", "/tmp/x.json", "--field", "ism"])
    assert a.output == "/tmp/x.json"
    assert a.field == "ism"


def test_parse_args_requires_values():
    with pytest.raises(SystemExit):
        P.parse_args(["--threshold"])           # missing value
    with pytest.raises(SystemExit):
        P.parse_args(["--bogus-flag"])          # unknown flag


def test_parse_args_extras_implies_toolkit_flags(capsys):
    # --extras is expanded in main(), not parse_args; verify the flag parses
    a = P.parse_args(["--extras"])
    assert a.extras is True


# ---------------------------------------------------------------------------
# main() — offline entry points
# ---------------------------------------------------------------------------
def test_main_list_sources_prints_every_source(capsys):
    rc = P.main(["--list-sources"])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("aas", "euraxess", "nature_careers", "findaphd", "eso"):
        assert name in out


def test_main_list_fields_prints_profiles(capsys):
    rc = P.main(["--list-fields"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Available field profiles" in out
    assert "astronomy" in out


def test_main_self_test_returns_zero(capsys):
    rc = P.main(["--self-test"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SELF-TEST: ALL PASSED" in out


def test_main_self_test_with_no_config(capsys):
    rc = P.main(["--self-test", "--no-config"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SELF-TEST: ALL PASSED" in out


def test_main_find_supervisors_without_country_fails(capsys):
    rc = P.main(["--find-supervisors"])
    out = capsys.readouterr().err + capsys.readouterr().out
    assert rc == 2                       # missing --country -> usage error


def test_main_new_field_rejects_bad_name(capsys):
    rc = P.main(["--new-field", "Bad Name!"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "Please pass a profile name" in out


def test_main_new_field_conflict_returns_two(tmp_path, monkeypatch, capsys):
    # a name that already resolves to an existing profile file
    rc = P.main(["--new-field", "astronomy"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "already exists" in out


# ---------------------------------------------------------------------------
# do_list_sources / new_field_wizard internals
# ---------------------------------------------------------------------------
def test_do_list_sources_lists_playwright_capability(capsys):
    P.do_list_sources(P.build_config(argparse.Namespace(no_config=True)))
    out = capsys.readouterr().out
    assert "Registered sources" in out
    assert "curl_cffi" in out


def test_new_field_wizard_requires_core_anchor(monkeypatch, capsys, tmp_path):
    import os
    answers = iter(["A test major", ""])   # description, then blank -> no anchors
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    monkeypatch.setattr(P, "FIELDS_DIR", str(tmp_path))
    rc = P.new_field_wizard("zzz_field_test")
    out = capsys.readouterr().out
    assert rc == 1
    assert "Need at least one core anchor" in out
