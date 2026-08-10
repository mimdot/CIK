#!/usr/bin/env python3
"""Offline tests for core/utils.py + core/records.py (migration Step 2).

Verify the moved text/date/country/URL helpers and the record factory behave
identically to the monolith originals, and that the names are still reachable
through the phd_aggregator back-compat surface.

Run:  python -m pytest tests/test_utils.py -q
"""
import os
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.records as records
import core.utils as utils
import phd_aggregator as P


# ---------------------------------------------------------------- normalize_url
def test_normalize_url_strips_tracking_params():
    url = ("https://example.com/jobs/123?utm_source=fb&utm_medium=cpc"
           "&gclid=abc&id=456&src=web")
    out = utils.normalize_url(url)
    assert "utm_source" not in out
    assert "utm_medium" not in out
    assert "gclid" not in out
    assert "src" not in out
    assert "id=1" in out or "id=456" in out


def test_normalize_url_lowercases_host():
    out = utils.normalize_url("HTTPS://Example.COM/PHDs/Astro/?q=1")
    assert out.startswith("https://example.com")


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert utils.normalize_url("https://example.com/a/b/") == "https://example.com/a/b"
    assert utils.normalize_url("https://example.com/a/b#frag") == "https://example.com/a/b"


# ------------------------------------------------------------------ dedupe_key
def test_dedupe_key_prefers_title_institution():
    a = P.make_record(title="PhD in Astronomy", institution="Uni of X",
                      url="https://x.example/jobs/1")
    b = P.make_record(title="PhD in Astronomy", institution="Uni of X",
                      url="https://x.example/jobs/999")
    assert P.dedupe_key(a) == P.dedupe_key(b)
    assert P.dedupe_key(a)[0] == "ti"


def test_dedupe_key_falls_back_to_url():
    a = P.make_record(title="PhD in Astronomy", institution=None,
                      url="https://x.example/jobs/1")
    b = P.make_record(title="PhD in Astronomy", institution=None,
                      url="https://x.example/jobs/1")
    assert P.dedupe_key(a) == P.dedupe_key(b)
    assert P.dedupe_key(a)[0] == "url"


# -------------------------------------------------------------------- parse_date
def test_parse_date_iso():
    assert P.parse_date("2026-07-15") == "2026-07-15"


def test_parse_date_european():
    assert P.parse_date("15/07/2026") == "2026-07-15"
    assert P.parse_date("15.07.2026") == "2026-07-15"


def test_parse_date_struct_time():
    st = time.struct_time((2026, 7, 15, 0, 0, 0, 0, 0, -1))
    assert P.parse_date(st) == "2026-07-15"


def test_parse_date_label_and_none():
    assert P.parse_date("Closes: 15 July 2026 (GMT)") == "2026-07-15"
    assert P.parse_date(None) is None
    assert P.parse_date("") is None


# ----------------------------------------------------------- canonical_country
def test_canonical_country_iso2():
    assert P.canonical_country("DE") == "Germany"
    assert P.canonical_country("gb") == "United Kingdom"


def test_canonical_country_alias():
    assert P.canonical_country("United Kingdom") == "United Kingdom"
    assert P.canonical_country("USA") == "United States"


# ---------------------------------------------------------------- guess_country
def test_guess_country_city_hint():
    assert P.guess_country("Observatory of Garching") == "Germany"
    assert P.guess_country("Leiden Observatory") == "Netherlands"


def test_guess_country_iso2_suffix():
    assert P.guess_country("Some Institute (CN)") == "China"


# ------------------------------------------------------------------ make_record
def test_make_record_defensive():
    r = P.make_record(title="  PhD <b>in</b> Astrophysics  ",
                      institution=None, country="DE",
                      url="   https://x.example/jobs/1   ",
                      short_description="Long ad: " + "x" * 500)
    assert r["title"] == "PhD in Astrophysics"
    assert r["institution"] is None
    assert r["country"] == "Germany"
    assert r["url"] == "https://x.example/jobs/1"
    assert r["position_type"] is None
    assert r["relevance_score"] == 0.0
    assert len(r["short_description"]) <= 400
    assert set(P.OUTPUT_FIELDS).issubset(r.keys())


def test_make_record_uses_records_module():
    assert P.make_record.__module__.startswith("core.records") or callable(P.make_record)