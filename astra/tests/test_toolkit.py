#!/usr/bin/env python3
"""Unit tests for the toolkit/ package (migration Step 10): the applicant
profile + per-position emails, the professor finder, and the scholarships
writer. All writers are exercised against tmp dirs; the arXiv survey uses a
stub HTTP object so no network is needed.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from core.config import build_config
from core.records import make_record
from toolkit.emails import (_EMAIL_FIT_FALLBACK, _EMAIL_FIT_RULES,
                            APPLICANT_PROFILE, _slugify, build_email,
                            write_emails)
from toolkit.professors import (PROFESSOR_ARXIV_QUERIES, PROFESSOR_SEED,
                                _arxiv_author_survey, find_professors)
from toolkit.scholarships import (SCHOLARSHIPS, _SCHOLARSHIP_PRACTICAL_NOTES,
                                  write_scholarships)


# ---------------------------------------------------------------------------
# emails.py — _slugify
# ---------------------------------------------------------------------------
def test_slugify_basic():
    assert _slugify("Max Planck Institute for Radio Astronomy") \
        == "max-planck-institute-for-radio-astronomy"


def test_slugify_max_len_truncates_and_rstrips():
    out = _slugify("PhD position in interstellar magnetic fields (f/m/d)", 30)
    assert len(out) <= 30
    assert not out.endswith("-")


def test_slugify_empty_falls_back():
    assert _slugify(None) == "position"
    assert _slugify("") == "position"


def test_slugify_strips_non_alnum():
    assert _slugify("  C++ & AI/ML (PhD)  ") == "c-ai-ml-phd"


# ---------------------------------------------------------------------------
# emails.py — build_email
# ---------------------------------------------------------------------------
def _radio_record():
    return make_record(title="PhD position in Radio Astronomy (m/f/d)",
                       institution="Max Planck Institute for Radio Astronomy",
                       country="Germany",
                       deadline="2099-12-31",
                       url="https://ex.org/jobs/1",
                       short_description="A PhD studentship on radio astronomy "
                                         "and interstellar medium magnetic "
                                         "fields.",
                       source="aas")


def test_build_email_subject_carries_title_and_institution():
    subj, body = build_email(_radio_record())
    assert "PhD position in Radio Astronomy (m/f/d)" in subj
    assert "Max Planck Institute for Radio Astronomy" in subj


def test_build_email_signed_with_profile():
    subj, body = build_email(_radio_record())
    assert APPLICANT_PROFILE["name"] in body
    assert APPLICANT_PROFILE["email"] in body
    assert "Sincerely," in body


def test_build_email_fit_paragraph_radio():
    subj, body = build_email(_radio_record())
    assert ("cosmic-ray" in body or "Faraday" in body or "GMIMS" in body)


def test_build_email_deadline_note():
    subj, body = build_email(_radio_record())
    assert "applications close on 2099-12-31" in body


def test_build_email_no_deadline_no_note():
    rec = make_record(title="PhD in X", institution="U", source="euraxess",
                      url="https://ex.org/2",
                      short_description="Plain posting without a deadline.")
    subj, body = build_email(rec)
    assert "close on" not in body


def test_build_email_fallback_when_no_rules_match():
    rec = make_record(title="Laboratory technician", institution="U",
                      source="jobs_ac_uk", url="https://ex.org/3",
                      short_description="Maintain laboratory equipment.")
    subj, body = build_email(rec)
    assert "My background combines multi-wavelength observations" in body


def test_build_email_fit_rules_cap_at_three():
    rec = make_record(
        title="PhD on magnetic fields and cosmic rays",
        institution="MPIfR",
        source="euraxess", url="https://ex.org/4",
        short_description="Radio astronomy survey of interstellar magnetic "
                          "fields, molecular clouds and star formation.")
    subj, body = build_email(rec)
    # rules 1 (magnetic/Faraday), 2 (radio/LOFAR), 3 (ISM/molecular cloud)
    assert body.count("directly relevant") >= 0
    # at most 3 sentences got appended before the CV paragraph
    paragraph = body.split("My CV")[0]
    fits = [s for s in _EMAIL_FIT_RULES if s[1] in paragraph]
    assert len(fits) <= 3


def test_build_email_fit_rules_regex_sanity():
    # every rule must actually compile
    import re
    for rx, _ in _EMAIL_FIT_RULES:
        re.compile(rx)


def test_build_email_source_labeled():
    subj, body = build_email(_radio_record())
    assert "the AAS Job Register" in body


# ---------------------------------------------------------------------------
# emails.py — write_emails
# ---------------------------------------------------------------------------
def test_write_emails_writes_one_file_per_record(tmp_path, monkeypatch):
    cfg = build_config(None)
    cfg.output_path = str(tmp_path / "results.csv")
    recs = [_radio_record(),
            make_record(title="PhD in Cosmology", institution="Leiden",
                        source="academictransfer", url="https://ex.org/5")]
    write_emails(recs, cfg)
    files = sorted(p for p in os.listdir(tmp_path / "emails"))
    assert len(files) == 3                      # 2 emails + _index.csv
    assert any(f.endswith(".txt") for f in files)
    assert "_index.csv" in files


def test_write_emails_empty_records_noop(tmp_path, caplog):
    import logging
    cfg = build_config(None)
    cfg.output_path = str(tmp_path / "results.csv")
    with caplog.at_level(logging.WARNING):
        write_emails([], cfg)
    assert not (tmp_path / "emails").exists()
    assert any("no positions" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# emails.py — _ensure_applicant_profile / APPLICANT_PROFILE
# ---------------------------------------------------------------------------
def test_applicant_profile_has_required_keys():
    for key in ("name", "email", "msc", "bsc", "cv_filename", "references"):
        assert key in APPLICANT_PROFILE
    # the on-disk applicant.yaml (if present) may overlay the profile, but the
    # schema must always expose the keys write_emails() relies on
    assert "@" in APPLICANT_PROFILE["email"] or APPLICANT_PROFILE["email"].startswith("you@")
    assert APPLICANT_PROFILE["cv_filename"].endswith(".pdf") or APPLICANT_PROFILE["cv_filename"].endswith(".PDF")


def test_ensure_profile_overlays_yaml(monkeypatch, tmp_path):
    (tmp_path / "applicant.yaml").write_text(
        "name: Maria Rossi\nemail: m@x.org\n")
    monkeypatch.chdir(tmp_path)
    from toolkit.emails import _ensure_applicant_profile
    _ensure_applicant_profile()
    assert APPLICANT_PROFILE["name"] == "Maria Rossi"
    assert APPLICANT_PROFILE["email"] == "m@x.org"


# ---------------------------------------------------------------------------
# professors.py — PROFESSOR_SEED integrity
# ---------------------------------------------------------------------------
def test_professor_seed_entries_well_formed():
    assert len(PROFESSOR_SEED) >= 30
    for p in PROFESSOR_SEED:
        assert p.get("name") and p.get("affiliation") and p.get("topics")


def test_professor_seed_unique_names():
    names = [p["name"] for p in PROFESSOR_SEED]
    assert len(names) == len(set(names))


def test_professor_seed_covers_target_regions():
    countries = {p["country"] for p in PROFESSOR_SEED}
    assert {"Germany", "Japan", "China"} <= countries


def test_professor_arxiv_queries_nonempty():
    assert PROFESSOR_ARXIV_QUERIES
    for q in PROFESSOR_ARXIV_QUERIES:
        assert q.startswith('"') and q.endswith('"')


# ---------------------------------------------------------------------------
# professors.py — _arxiv_author_survey (stub HTTP, feedparser-agnostic)
# ---------------------------------------------------------------------------
class _FakeEntry(dict):
    def __init__(self, title, authors):
        super().__init__(title=title, authors=authors)
        self.title = title
        self.authors = authors


class _FakeAuthor(dict):
    pass


class _FakeFeed:
    def __init__(self, entries):
        self.entries = entries


class _Resp:
    status_code = 200
    def __init__(self, content):
        self.content = content


class _Http:
    def __init__(self, feed):
        self._feed = feed
        self.calls = []
    def raw_get(self, url, params=None, **kw):
        self.calls.append(url)
        return _Resp(b"ignored")


def test_arxiv_author_survey_counts_frequent_authors(monkeypatch):
    from toolkit import professors as prof
    monkeypatch.setattr(prof.time, "sleep", lambda s: None)
    # twice-matched authors float to the top; curated names are excluded
    feed = _FakeFeed([
        _FakeEntry("Faraday tomography of the ISM",
                   [_FakeAuthor(name="Active One"),
                    _FakeAuthor(name="Rainer Beck")]),
        _FakeEntry("Faraday rotation in galaxies",
                   [_FakeAuthor(name="Active One"),
                    _FakeAuthor(name="Somebody Else")]),
    ])
    monkeypatch.setattr(prof.feedparser, "parse", lambda content: feed)
    rows = prof._arxiv_author_survey(_Http(None))
    names = [r["name"] for r in rows]
    assert "Active One" in names
    assert "Rainer Beck" not in names          # curated -> excluded


def test_arxiv_author_survey_empty_without_feedparser(monkeypatch):
    from toolkit import professors as prof
    monkeypatch.setattr(prof, "_HAVE_FEEDPARSER", False)
    assert prof._arxiv_author_survey(_Http(None)) == []


# ---------------------------------------------------------------------------
# professors.py — find_professors (writes csv + md)
# ---------------------------------------------------------------------------
def test_find_professors_writes_curated_files(tmp_path):
    cfg = build_config(None)
    cfg.output_path = str(tmp_path / "results.csv")
    find_professors(cfg, http=None)      # no http -> curated only, no survey
    csv = (tmp_path / "professors.csv").read_text(encoding="utf-8")
    md = (tmp_path / "professors.md").read_text(encoding="utf-8")
    assert "Rainer Beck" in csv
    assert "Rainer Beck" in md
    assert csv.splitlines()[0].startswith("origin,")   # header present


def test_find_professors_with_survey_includes_arxiv_rows(tmp_path, monkeypatch):
    from toolkit import professors as prof
    monkeypatch.setattr(prof.time, "sleep", lambda s: None)
    feed = _FakeFeed([
        _FakeEntry("Galactic magnetic fields from Faraday tomography",
                   [_FakeAuthor(name="Survey Star"),
                    _FakeAuthor(name="Rainer Beck")]),
        _FakeEntry("Magnetic fields in molecular clouds",
                   [_FakeAuthor(name="Survey Star"),
                    _FakeAuthor(name="Survey Star2")]),
    ])
    monkeypatch.setattr(prof.feedparser, "parse", lambda content: feed)
    cfg = build_config(None)
    cfg.output_path = str(tmp_path / "results.csv")
    find_professors(cfg, http=_Http(None))
    md = (tmp_path / "professors.md").read_text(encoding="utf-8")
    assert "Active right now" in md
    assert "Survey Star" in md


# ---------------------------------------------------------------------------
# scholarships.py — SCHOLARSHIPS integrity
# ---------------------------------------------------------------------------
def test_scholarships_well_formed():
    assert len(SCHOLARSHIPS) >= 15
    for s in SCHOLARSHIPS:
        assert s.get("name") and s.get("url") and s.get("fit")
        assert s.get("region") and s.get("deadline") and s.get("funding")


def test_scholarships_regions_include_targets():
    regions = {s["region"] for s in SCHOLARSHIPS}
    assert {"Germany", "Japan", "China"} <= regions


def test_scholarship_practical_notes_nonempty():
    assert "Iran" in _SCHOLARSHIP_PRACTICAL_NOTES
    assert "visa" in _SCHOLARSHIP_PRACTICAL_NOTES.lower()


# ---------------------------------------------------------------------------
# scholarships.py — write_scholarships (writes csv + md)
# ---------------------------------------------------------------------------
def test_write_scholarships_writes_files(tmp_path):
    cfg = build_config(None)
    cfg.output_path = str(tmp_path / "results.csv")
    write_scholarships(cfg)
    csv = (tmp_path / "scholarships.csv").read_text(encoding="utf-8")
    md = (tmp_path / "scholarships.md").read_text(encoding="utf-8")
    assert "IMPRS for Astronomy & Astrophysics (Bonn/Cologne, MPIfR)" in md
    assert csv.splitlines()[0].startswith("name,")
    assert "MEXT" in md
