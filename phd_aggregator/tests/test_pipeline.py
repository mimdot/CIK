#!/usr/bin/env python3
"""Offline unit tests for the phd_aggregator pipeline core.

Covers the pure/composable pieces of the monolith that self_test() exercises
only implicitly (and only when a human runs it): relevance scoring, dedupe,
the freshness layer, state persistence, the email builder, position-type
classification, country geolocation, and the HTML parsers behind the
source scrapers. No network, no Playwright, no applicant.yaml.

Run:  python -m pytest tests/test_pipeline.py -q
"""
import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phd_aggregator as P

from core.deps import _HTML_PARSER
from sources.academictransfer import _academictransfer_ssr_fallback
from toolkit import _ensure_applicant_profile


def _cfg(**kwargs):
    base = dict(no_config=True, debug=False, phd_only=False, field=None)
    base.update(kwargs)
    return P.build_config(argparse.Namespace(**base))


def _rec(**kw):
    defaults = dict(title="PhD in stellar astrophysics", institution="MPIfR",
                    country="Germany", url="https://ex.org/j/1",
                    source="euraxess")
    defaults.update(kw)
    return P.make_record(**defaults)


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------
def test_score_title_anchor_beats_description_only():
    cfg = _cfg()
    t_score, t_anchors, _, _ = P.score_relevance(
        "PhD position in radio astronomy", "Lots of text.", cfg)
    d_score, d_anchors, _, _ = P.score_relevance(
        "PhD position somewhere", "Work on radio astronomy.", cfg)
    assert t_score > d_score
    assert d_score >= cfg.threshold          # a desc-only anchor still passes
    assert P.is_relevant(t_score, t_anchors, cfg)
    assert P.is_relevant(d_score, d_anchors, cfg)


def test_context_only_never_qualifies():
    cfg = _cfg()
    score, anchors, _, _ = P.score_relevance(
        "PhD in simulation and data analysis", "Theoretical methods.", cfg)
    assert not anchors
    assert not P.is_relevant(score, anchors, cfg)


def test_negative_terms_demote_but_title_anchor_overrides():
    cfg = _cfg()
    # negative (quantum ...) without a core anchor -> rejected
    s, a, _, n = P.score_relevance("PhD in quantum optics and photonic circuits",
                                   "", cfg)
    assert not a and n
    assert not P.is_relevant(s, a, cfg)
    # genuine crossover: core anchor in TITLE beats negatives
    s2, a2, _, n2 = P.score_relevance(
        "PhD in radio astronomy",
        "Apply quantum computing and quantum information methods.", cfg)
    assert a2 and n2
    assert P.is_relevant(s2, a2, cfg)


def test_require_title_anchor_gate():
    cfg = _cfg()
    cfg.require_title_anchor = True
    score, anchors, _, _ = P.score_relevance(
        "PhD position somewhere", "Strong astronomy methods.", cfg)
    assert not P.is_relevant(score, anchors, cfg,
                             title_anchors=[])
    # explicit title anchor present -> qualifies
    ttl = [t for t, rx in cfg._core_rx if rx.search("PhD in astronomy")]
    assert P.is_relevant(score, anchors, cfg, title_anchors=ttl)


def test_case_sensitive_acronym_terms():
    cfg = _cfg()
    # ISM must not fire inside "mechanism"
    assert not [t for t, rx in cfg._core_rx
                if t == "ISM" and rx.search("the mechanism is simple")]
    assert [t for t, rx in cfg._core_rx
            if t == "ISM" and rx.search("interstellar medium (ISM)")]


# ---------------------------------------------------------------------------
# Position-type classification
# ---------------------------------------------------------------------------
def test_classify_phd_vs_postdoc():
    assert P.classify_position_type("PhD position in cosmology", "") == "phd"
    assert P.classify_position_type("Doctoral researcher, galaxies", "") == "phd"
    # the historical leak: post-doctoral must NOT classify as phd
    assert (P.classify_position_type("Post Doctoral Research Associate", "")
            == "postdoc")
    assert P.classify_position_type("Postdoc on magnetic fields", "") == "postdoc"
    assert P.classify_position_type("Professor of Astrophysics", "") == "faculty"
    assert P.classify_position_type("Research Engineer", "") == "staff"


def test_phd_requirement_noise_stripped_from_description():
    # "must hold a PhD" in the description is a postdoc ad, not a PhD opening
    t = P.classify_position_type("Research Associate in Solar Physics",
                                 "Candidates must hold a PhD.")
    assert t == "postdoc"


# ---------------------------------------------------------------------------
# Country geolocation
# ---------------------------------------------------------------------------
def test_canonical_country_variants():
    assert P.canonical_country("uk") == "United Kingdom"
    assert P.canonical_country("DE") == "Germany"    # ISO2 codes are mapped
    assert P.canonical_country("south korea") == "South Korea"
    assert P.canonical_country("") is None


def test_guess_country_free_text():
    assert P.guess_country("based at LMU Munich, Germany") == "Germany"
    assert P.guess_country("located in Leiden, Netherlands") == "Netherlands"
    assert P.guess_country("nothing relevant here") is None


# ---------------------------------------------------------------------------
# URL normalization + dedupe
# ---------------------------------------------------------------------------
def test_normalize_url_strips_tracking():
    a = P.normalize_url("https://Ex.org/j/9/?utm_source=a&x=1#frag")
    b = P.normalize_url("https://ex.org/j/9?x=1")
    assert a == b
    assert "utm" not in (a or "")


def test_dedupe_same_url_merges_sources():
    r1 = _rec(title="PhD in cosmology X", institution="Swansea",
              url="https://ex.org/j/9?utm_source=a", source="euraxess")
    r2 = _rec(title="PhD in cosmology X", institution=None,
              url="https://ex.org/j/9", source="seed_urls")
    merged = P.dedupe_records([r1, r2])
    assert len(merged) == 1
    assert merged[0]["institution"] == "Swansea"
    assert "euraxess" in merged[0]["source"] and "seed_urls" in merged[0]["source"]


def test_dedupe_title_plus_institution():
    r1 = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
              url="https://a.org/1")
    r2 = _rec(title="PhD in Stellar Astrophysics !", institution="mpifr",
              url="https://b.org/2")
    assert len(P.dedupe_records([r1, r2])) == 1


def test_dedupe_keeps_distinct_jobs():
    a = _rec(title="PhD in stellar astrophysics", institution="MPIfR",
             url="https://a.org/1")
    b = _rec(title="PhD in cosmology", institution="MPIfR",
             url="https://a.org/2")
    assert len(P.dedupe_records([a, b])) == 2


# ---------------------------------------------------------------------------
# Freshness layer + state persistence
# ---------------------------------------------------------------------------
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

    kept = P.apply_freshness([r_old, r_old_dl, r_undated, r_month], cfg, state,
                             today=today)
    urls = {r["url"] for r in kept}
    assert "https://ex.org/f/old" not in urls          # stale, no deadline
    assert "https://ex.org/f/olddl" in urls            # future deadline keeps
    assert "https://ex.org/f/undated" in urls          # kept on first discovery
    assert "https://ex.org/f/new" in urls
    undated = next(r for r in kept if r["url"].endswith("/undated"))
    assert undated["freshness"] == "undated_new"

    # a simulated run 401 days later ages the undated post out via first_seen
    later = today + _dt.timedelta(days=401)
    kept2 = P.apply_freshness([_rec(title="PhD in stellar astrophysics",
                                    url="https://ex.org/f/undated")],
                              cfg, state, today=later)
    assert not kept2


def test_save_state_is_atomic_and_roundtrips(tmp_path):
    cfg = _cfg()
    cfg.state_path = os.path.join(str(tmp_path), "state.json")
    state = {"version": 1,
             "urls": {"https://ex.org/1": {"first_seen": "2026-01-01",
                                           "last_seen": "2026-02-01"}},
             "seed_domains": {}}
    P.save_state(state, cfg, today=_dt.date(2026, 3, 1))
    loaded = P.load_state(cfg)
    assert loaded["urls"]["https://ex.org/1"]["first_seen"] == "2026-01-01"
    assert not os.path.exists(cfg.state_path + ".tmp")   # temp cleaned up


def test_save_state_prunes_stale_urls(tmp_path):
    cfg = _cfg()
    cfg.max_age_days = 30
    cfg.state_path = os.path.join(str(tmp_path), "state.json")
    today = _dt.date(2026, 3, 1)
    state = {"version": 1, "urls": {
        # last seen 2 years ago -> pruned (2 * max(30, 30) days window)
        "https://ex.org/old": {"first_seen": "2024-01-01", "last_seen": "2024-02-01"},
        # recent -> kept
        "https://ex.org/new": {"first_seen": "2026-02-01", "last_seen": "2026-02-15"},
    }, "seed_domains": {}}
    P.save_state(state, cfg, today=today)
    loaded = P.load_state(cfg)
    assert "https://ex.org/old" not in loaded["urls"]
    assert "https://ex.org/new" in loaded["urls"]


# ---------------------------------------------------------------------------
# Email builder
# ---------------------------------------------------------------------------
def test_build_email_carries_position_and_profile():
    _ensure_applicant_profile()
    record = _rec(title="PhD position in radio astronomy",
                  institution="Max Planck Institute for Radio Astronomy",
                  url="https://ex.org/j/1",
                  short_description="LOFAR cosmic-ray mapping project.")
    subj, body = P.build_email(record)
    assert record["title"] in subj
    assert "Max Planck" in subj
    assert P.APPLICANT_PROFILE["name"] in body
    assert P.APPLICANT_PROFILE["email"] in body


# ---------------------------------------------------------------------------
# HTML parsing used by the seed_urls source (and the SSR fallback)
# ---------------------------------------------------------------------------
JSONLD_FIXTURE = """<!doctype html><html><head>
  <title>Fallback title — Some Board</title>
  <meta property="og:title" content="OG title (must lose to JSON-LD)">
  <script type="application/ld+json">
  {"@context": "https://schema.org", "@graph": [
    {"@type": "BreadcrumbList", "itemListElement": []},
    {"@type": "JobPosting",
     "title": "PhD position in interstellar magnetic fields (f/m/d)",
     "hiringOrganization": {"@type": "Organization",
                            "name": "Example Institute for Astrophysics"},
     "jobLocation": [{"@type": "Place",
                      "address": {"@type": "PostalAddress",
                                  "addressLocality": "Bonn",
                                  "addressCountry": "DE"}}],
     "datePosted": "2026-06-15",
     "validThrough": "2026-09-30T23:59",
     "description": "<p>Doctoral project on <b>Faraday rotation</b> and the interstellar medium of nearby galaxies.</p>"}]}
  </script></head>
  <body><main>Apply by the deadline. Posted on 15 June 2026.</main></body>
  </html>"""


def test_parse_position_page_jsonld_beats_og():
    rec = P.parse_position_page(JSONLD_FIXTURE, "https://ex.org/jobs/42",
                                "seed_urls")
    assert rec is not None
    assert rec["title"] == "PhD position in interstellar magnetic fields (f/m/d)"
    assert rec["institution"] == "Example Institute for Astrophysics"
    assert rec["deadline"] == "2026-09-30"
    assert rec["posted_date"] == "2026-06-15"
    assert rec.get("_parsed_from") == "jsonld"
    assert "Faraday" in (rec["short_description"] or "")
    assert "Bonn" in (rec["raw_location"] or "")


def test_parse_position_page_og_fallback():
    html = ("<html><head><title>t</title>"
            "<meta property='og:title' content='PhD studentship in cosmology'>"
            "<meta property='og:description' content='CMB analysis project.'>"
            "</head><body><p>Apply by: 15 August 2099.</p></body></html>")
    rec = P.parse_position_page(html, "https://ex.org/jobs/43")
    assert rec is not None
    assert rec["title"] == "PhD studentship in cosmology"
    assert rec["deadline"] == "2099-08-15"


def test_parse_position_page_rejects_untitled():
    assert P.parse_position_page("<html><body><p>nothing here</p></body></html>",
                                 "https://ex.org/x") is None


def test_extract_page_date_from_posted_line():
    html = "<html><body><p>Position posted on 12 June 2026.</p></body></html>"
    assert P.extract_page_date(html) == "2026-06-12"
    assert P.extract_page_date("<html></html>") is None


def test_academictransfer_ssr_fallback_parses_links():
    html = ("<html><body>"
            "<a href='/en/jobs/361520/phd-position-in-astronomy/'>PhD in astronomy</a>"
            "<a href='/en/jobs/361521/'>Other post</a>"
            "</body></html>")
    soup = P.BeautifulSoup(html, _HTML_PARSER)

    class _FakeHttp:
        def get_soup(self, url, **kw):
            return soup

    records = _academictransfer_ssr_fallback(_cfg(), _FakeHttp())
    assert len(records) == 2
    assert records[0]["title"] == "PhD in astronomy"
    assert records[0]["url"].startswith("https://www.academictransfer.com")
    assert records[0]["country"] == "Netherlands"
    assert records[0]["source"] == "academictransfer"
    # slug-derived title when the link has no anchor text
    assert records[1]["title"] == "Other post"


# ---------------------------------------------------------------------------
# filter_records (type + relevance + expiry + region gates)
# ---------------------------------------------------------------------------
def test_filter_records_gates_and_precedence():
    cfg = _cfg()
    cfg.countries = ["Germany"]
    cfg.exclude_expired = True
    good = _rec(title="PhD in radio astronomy", institution="MPIfR",
                country="Germany", deadline="2099-12-31")
    # postdoc dropped by the type gate
    bad_type = _rec(title="Postdoc in radio astronomy", institution="MPIfR",
                    country="Germany", deadline="2099-12-31")
    # irrelevant dropped by the relevance gate
    bad_rel = _rec(title="Administrative assistant", institution="MPIfR",
                   country="Germany", deadline="2099-12-31")
    # expired dropped by the expiry gate
    expired = _rec(title="PhD in radio astronomy", institution="MPIfR",
                   country="Germany", deadline="2001-01-01")
    # wrong country dropped by the geo gate
    bad_geo = _rec(title="PhD in radio astronomy", institution="MPIfR",
                   country="France", deadline="2099-12-31")
    kept = P.filter_records([good, bad_type, bad_rel, expired, bad_geo], cfg)
    assert [r["title"] for r in kept] == [good["title"]]
    assert kept[0]["position_type"] == "phd"
    assert kept[0]["country"] == "Germany"
    assert kept[0]["relevance_score"] >= cfg.threshold


def test_filter_country_hint_beats_board_default():
    cfg = _cfg()
    cfg.countries = ["Germany"]
    r = _rec(title="PhD in radio astronomy", institution="MPIfR",
             country="France",          # board-provided default (would drop)
             country_hint="Bonn, Germany",  # explicit hint wins
             deadline="2099-12-31")
    kept = P.filter_records([r], cfg)
    assert len(kept) == 1
    assert kept[0]["country"] == "Germany"


def test_filter_seed_bypass_gate():
    cfg = _cfg()
    cfg.seed_bypass_gate = True
    seed = _rec(title="Postdoctoral fellow in galactic magnetism",
                institution="MPIfR", country="Germany",
                short_description="Postdoc on magnetic fields in galaxies.",
                url="https://ex.org/seed/pd")
    seed["_seed"] = True
    kept = P.filter_records([seed], cfg)
    assert len(kept) == 1 and kept[0]["position_type"] == "postdoc"
    cfg.seed_bypass_gate = False
    assert not P.filter_records([seed], cfg)


# ---------------------------------------------------------------------------
# make_record schema guarantees
# ---------------------------------------------------------------------------
def test_make_record_schema_complete():
    rec = _rec()
    for field in P.OUTPUT_FIELDS:
        assert field in rec, field
    assert rec["url"].strip() == "https://ex.org/j/1"
    assert rec["relevance_score"] == 0.0
    assert rec["matched_anchors"] == []
    assert rec["is_new"] is False
    assert rec["freshness"] is None
