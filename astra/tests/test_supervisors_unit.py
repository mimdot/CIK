#!/usr/bin/env python3
"""Unit tests for the supervisors/ package (migration Step 9).

Aggregation/name-merge/country-filter/ranking logic is tested directly against
fixture docs (no network); the HTTP-facing OpenAlex/arXiv/ADS/orcid paths use
stub HTTP objects. Mirrors the coverage that used to live inside the monolith's
--self-test, now as real unit tests.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.config import (SUPERVISOR_MAX_AUTHORS, SUPERVISOR_MIN_PAPERS,
                         SUPERVISOR_SENIOR_WEIGHT, _CANON_TO_ISO2,
                         build_config)
from supervisors.aggregate import _author_key, _paper_link, aggregate_supervisors
from supervisors.chain import (AUTHOR_SEARCH_FMT, _load_dotenv,
                               _orcid_public_email, _supervisor_chain,
                               _supervisor_focus, write_supervisors_html)
from supervisors.openalex import (_author_current_institution,
                                  _openalex_author_records,
                                  _openalex_author_recent,
                                  _openalex_works_pool,
                                  openalex_supervisor_authors)
import argparse


# ---------------------------------------------------------------------------
# aggregate.py — _author_key (name-variant normalization)
# ---------------------------------------------------------------------------
def test_author_key_full_variant():
    assert _author_key("Beck, Rainer") == "beck, r"


def test_author_key_initial_variant_merges():
    assert _author_key("Beck, R.") == "beck, r"


def test_author_key_first_last_form():
    assert _author_key("Rainer Beck") == "beck, r"


def test_author_key_ascii_fold():
    assert _author_key("Chyży, Krzysztof") == "chyzy, k"


def test_author_key_empty_returns_none():
    assert _author_key("") is None
    assert _author_key("  ") is None


def test_author_key_no_first_name():
    assert _author_key("Beck") == "beck"


# ---------------------------------------------------------------------------
# aggregate.py — _paper_link
# ---------------------------------------------------------------------------
def test_paper_link_ads_bibcode_wins():
    assert _paper_link("2025A&A...1..123", None, "10.1/x") \
        == "https://ui.adsabs.harvard.edu/abs/2025A%26A...1..123/abstract"


def test_paper_link_bare_doi():
    assert _paper_link(None, None, "10.1000/xyz") == "https://doi.org/10.1000/xyz"


def test_paper_link_full_url_doi():
    assert _paper_link(None, None, "https://doi.org/10.1/x") \
        == "https://doi.org/10.1/x"


def test_paper_link_plain_url_fallback():
    assert _paper_link(None, "https://ex.org/paper", None) == "https://ex.org/paper"


def test_paper_link_empty():
    assert _paper_link(None, None, None) == ""


# ---------------------------------------------------------------------------
# aggregate.py — aggregate_supervisors (pure aggregation + ranking)
# ---------------------------------------------------------------------------
def _doc(title, year, authors, affs):
    return {"title": title, "year": year, "authors": authors,
            "affs": affs, "orcids": [], "bibcode": None}


def test_aggregate_ranks_senior_author_first():
    docs = [
        _doc("Magnetic fields in M31", 2025,
             ["Student, A.", "Senior, Prof."],
             ["Univ. Bonn, Germany", "MPIfR, Bonn, Germany"]),
        _doc("Faraday rotation of M33", 2024,
             ["Other, B.", "Senior, P."],
             ["Univ. Koeln, Germany", "MPIfR, Bonn, Germany"]),
        _doc("Cosmic-ray transport in spirals", 2023,
             ["Senior, P.", "Someone, E."],
             ["MPIfR, Bonn, Germany", "IRAP, Toulouse, France"]),
    ]
    ranked = aggregate_supervisors(docs, "Germany",
                                   ["magnetic field", "Faraday rotation"],
                                   min_papers=2)
    assert ranked and ranked[0]["name"] == "Senior, Prof."
    assert ranked[0]["papers"] == 3
    assert ranked[0]["last_author_papers"] == 2


def test_aggregate_drops_oneoff_below_min_papers():
    docs = [_doc("Dust polarization survey", 2026,
                 ["Oneoff, C.", "Abroad, F."],
                 ["AIP, Potsdam, Germany", "IAP, Paris, France"])]
    assert aggregate_supervisors(docs, "Germany", ["dust"], min_papers=2) == []


def test_aggregate_excludes_out_of_country_author():
    docs = [
        _doc("Magnetised outflows", 2025,
             ["First, G.", "Abroad, F."],
             ["Univ. Hamburg, Germany", "IAP, Paris, France"]),
        _doc("More magnetised outflows", 2024,
             ["First, G.", "Abroad, F."],
             ["Univ. Hamburg, Germany", "IAP, Paris, France"]),
    ]
    ranked = aggregate_supervisors(docs, "Germany", ["magnet"], min_papers=2)
    names = [r["name"] for r in ranked]
    assert "Abroad, F." not in names
    assert ranked[0]["name"] == "First, G."
    assert ranked[0]["papers"] == 2


def test_aggregate_country_code_overrides_free_text():
    docs = [
        {"title": "T1", "year": 2025, "authors": ["Doe, J.", "Schmidt, A."],
         "affs": ["Univ. Paris, France", "LMU Munich, Germany"],
         "orcids": [], "author_countries": [["FR"], ["DE"]], "bibcode": None},
        {"title": "T2", "year": 2024, "authors": ["Doe, J.", "Mueller, B."],
         "affs": ["Univ. Paris, France", "TU Berlin, Germany"],
         "orcids": [], "author_countries": [["FR"], ["DE"]], "bibcode": None},
    ]
    ranked = aggregate_supervisors(docs, "Germany", ["machine learning"],
                                   min_papers=1)
    names = [r["name"] for r in ranked]
    assert "Doe, J." not in names
    assert "Schmidt, A." in names


def test_aggregate_senior_weight_zero_no_bonus():
    docs = [_doc("A", 2025, ["X, Y.", "Z, W."], ["Univ A, Germany", "Univ B, Germany"])]
    ranked = aggregate_supervisors(docs, "Germany", ["a"], min_papers=1,
                                   senior_weight=0.0)
    assert ranked and abs(ranked[0]["score"] - 1.0) < 0.001


def test_aggregate_senior_weight_default_adds_bonus():
    docs = [_doc("A", 2025, ["X, Y.", "Z, W."], ["Univ A, Germany", "Univ B, Germany"])]
    ranked = aggregate_supervisors(docs, "Germany", ["a"], min_papers=1)
    assert ranked and abs(ranked[0]["score"] -
                          (1.0 + SUPERVISOR_SENIOR_WEIGHT)) < 0.001


def test_aggregate_mega_collaboration_skipped():
    many = [f"Author{i}, X." for i in range(50)]
    docs = [_doc("Big collab paper", 2025, many,
                 [f"Inst {i}, Germany" for i in range(50)])]
    assert aggregate_supervisors(docs, "Germany", ["big"],
                                 max_authors=SUPERVISOR_MAX_AUTHORS) == []


def test_aggregate_default_ads_search_link():
    docs = [_doc("Magnetic fields in M31", 2025,
                 ["Senior, Prof."], ["MPIfR, Bonn, Germany"])]
    ranked = aggregate_supervisors(docs, "Germany", ["magnet"], min_papers=1)
    assert "adsabs.harvard.edu" in ranked[0]["author_search"]


def test_aggregate_openalex_search_link():
    docs = [_doc("Magnetic fields in M31", 2025,
                 ["Senior, Prof."], ["MPIfR, Bonn, Germany"])]
    ranked = aggregate_supervisors(docs, "Germany", ["magnet"], min_papers=1,
                                   search_fmt=AUTHOR_SEARCH_FMT["openalex"])
    assert "openalex.org" in ranked[0]["author_search"]


def test_aggregate_picks_most_common_affiliation():
    docs = [
        _doc("A", 2025, ["Sen, P."], ["Univ Bonn, Germany"]),
        _doc("B", 2024, ["Sen, P."], ["Univ Bonn, Germany"]),
        _doc("C", 2023, ["Sen, P."], ["MPIfR, Germany"]),
    ]
    ranked = aggregate_supervisors(docs, "Germany", ["a"], min_papers=2)
    assert ranked and "Univ Bonn" in ranked[0]["institution"]


def test_aggregate_docs_without_country_keeps_unverified():
    docs = [_doc("A", 2025, ["Sen, P."], ["Max Planck"])]
    ranked = aggregate_supervisors(docs, None, ["a"], min_papers=1)
    assert ranked and ranked[0]["country"] == "unverified"


def test_aggregate_topics_derived_from_matching_recent():
    docs = [_doc("Faraday rotation studies", 2025,
                 ["Sen, P."], ["MPIfR, Germany"])]
    ranked = aggregate_supervisors(docs, "Germany",
                                   ["Faraday rotation", "galactic dynamo"],
                                   min_papers=1)
    assert ranked and "Faraday rotation" in ranked[0]["topics"]


def test_aggregate_orcid_recorded():
    doc = _doc("A", 2025, ["Sen, P."], ["MPIfR, Germany"])
    doc["orcids"] = ["0000-0001-2345-6789"]
    ranked = aggregate_supervisors([doc], "Germany", ["a"], min_papers=1)
    assert ranked and ranked[0]["orcid"] == "0000-0001-2345-6789"
    assert ranked[0]["orcid_link"] == "https://orcid.org/0000-0001-2345-6789"


def test_aggregate_empty_docs_returns_empty():
    assert aggregate_supervisors([], "Germany", ["a"]) == []


# ---------------------------------------------------------------------------
# chain.py — _supervisor_chain (source selection)
# ---------------------------------------------------------------------------
def _mk_cfg(supervisor_source="auto", ads_db="astronomy"):
    cfg = build_config(argparse.Namespace(no_config=True))
    cfg.supervisor_source = supervisor_source
    cfg.supervisor_ads_db = ads_db
    return cfg


def test_chain_auto_astro_no_token():
    assert _supervisor_chain(_mk_cfg(), token=False) == ["openalex", "arxiv"]


def test_chain_auto_astro_with_token():
    assert _supervisor_chain(_mk_cfg(), token=True) == ["ads", "openalex"]


def test_chain_auto_nonastro_with_token():
    cfg = _mk_cfg(ads_db="general")
    assert _supervisor_chain(cfg, token=True) == ["openalex", "arxiv"]


def test_chain_forced_openalex():
    assert _supervisor_chain(_mk_cfg("openalex"), token=True) == ["openalex"]


def test_chain_forced_arxiv():
    assert _supervisor_chain(_mk_cfg("arxiv"), token=True) == ["arxiv"]


def test_chain_forced_ads_without_token_falls_back():
    assert _supervisor_chain(_mk_cfg("ads"), token=False) == ["openalex", "arxiv"]


# ---------------------------------------------------------------------------
# chain.py — _supervisor_focus (subfield -> label/keywords/topics)
# ---------------------------------------------------------------------------
def test_focus_subfield_topics_win():
    cfg = build_config(argparse.Namespace(no_config=True))
    cfg.subfield = "econ"
    cfg.subfields = {"econ": {"keywords": ["a"], "topics": ["T111"]}}
    label, kws, tp = _supervisor_focus(cfg)
    assert label == "econ" and kws == ["a"] and tp == ["T111"]


def test_focus_subfield_without_topics_falls_back():
    cfg = build_config(argparse.Namespace(no_config=True))
    cfg.subfield = "econ"
    cfg.subfields = {"econ": {"keywords": ["a"]}}
    cfg.supervisor_topics = ["T1", "T2"]
    _, _, tp = _supervisor_focus(cfg)
    assert tp == ["T1", "T2"]


def test_focus_whole_profile():
    cfg = build_config(argparse.Namespace(no_config=True))
    cfg.subfield = None
    label, kws, tp = _supervisor_focus(cfg)
    assert label == cfg.field_profile
    assert kws == list(cfg.search_terms)
    assert tp == list(cfg.supervisor_topics)


# ---------------------------------------------------------------------------
# chain.py — _orcid_public_email (stub HTTP)
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._p = payload

    def json(self):
        return self._p


class _Http:
    def __init__(self, resp):
        self._resp = resp
        self.last = None

    def raw_get(self, url, **kw):
        self.last = (url, kw)
        return self._resp


def test_orcid_email_returns_first_public_email():
    http = _Http(_Resp(200, {"email": [{"email": "a@x.org", "primary": False},
                                       {"email": "b@x.org", "primary": True}]}))
    assert _orcid_public_email(http, "0000-0001-2345-6789") == "a@x.org"


def test_orcid_email_none_on_http_error():
    http = _Http(_Resp(404, {}))
    assert _orcid_public_email(http, "0000-0001-2345-6789") is None


def test_orcid_email_none_on_garbage_json():
    http = _Http(_Resp(200, {"not_email": True}))
    assert _orcid_public_email(http, "0000-0001-2345-6789") is None


# ---------------------------------------------------------------------------
# chain.py — _load_dotenv (tmp .env)
# ---------------------------------------------------------------------------
def test_load_dotenv_reads_file(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nFOO=bar\nSPACED = 'quoted value'\nBAZ=wuz\n")
    monkeypatch.chdir(tmp_path)
    _load_dotenv()
    import os
    assert os.environ.get("FOO") == "bar"
    assert os.environ.get("SPACED") == "quoted value"


def test_load_dotenv_does_not_overwrite_existing(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("KEEP=fromfile\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KEEP", "already")
    _load_dotenv()
    import os
    assert os.environ.get("KEEP") == "already"


def test_load_dotenv_missing_file_is_noop(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _load_dotenv()   # no .env present -> must not raise


# ---------------------------------------------------------------------------
# chain.py — write_supervisors_html
# ---------------------------------------------------------------------------
def test_write_supervisors_html_writes_dashboard(tmp_path):
    rows = [{"name": "Rainer Beck", "score": 8.0, "papers": 5,
             "country": "Germany", "institution": "MPIfR",
             "topics": "magnetism", "representative_papers": "X (2025)",
             "author_search": "https://ui.adsabs.harvard.edu/search",
             "last_author_papers": 2, "orcid": "0000-0001", "rank": 1}]
    out = tmp_path / "sup.html"
    write_supervisors_html(rows, str(out), "astronomy", "Germany", "OpenAlex")
    html = out.read_text()
    assert "Rainer Beck" in html
    assert "astronomy / Germany" in html
    assert '"papers": 5' in html          # embedded JSON data payload


# ---------------------------------------------------------------------------
# openalex.py — _author_current_institution
# ---------------------------------------------------------------------------
def test_current_institution_prefers_recent_education():
    record = {"affiliations": [
        {"institution": {"display_name": "Think Tank", "type": "other",
                         "country_code": "GB"},
         "years": [2019, 2020]},
        {"institution": {"display_name": "LSE", "type": "education",
                         "country_code": "GB"},
         "years": [2022, 2023, 2024, 2025]},
    ]}
    assert _author_current_institution(record, "GB") == "LSE"


def test_current_institution_ignores_stale_and_foreign():
    record = {"affiliations": [
        {"institution": {"display_name": "Old School", "type": "education",
                         "country_code": "GB"},
         "years": [2010]},
        {"institution": {"display_name": "US Univ", "type": "education",
                         "country_code": "US"},
         "years": [2023, 2024, 2025]},
    ]}
    assert _author_current_institution(record, "GB") is None


def test_current_institution_empty_record():
    assert _author_current_institution({}, "GB") is None


# ---------------------------------------------------------------------------
# openalex.py — _openalex_works_pool (stub HTTP)
# ---------------------------------------------------------------------------
def _fake_resp(payload):
    class R:
        status_code = 200
        def __init__(self, p):
            self._p = p
        def json(self):
            return self._p
    return R(payload)


def _fake_http(responses):
    class H:
        def __init__(self, rs):
            self._rs = rs
            self.calls = []
        def raw_get(self, url, params=None, **kw):
            self.calls.append(params)
            return self._rs.pop(0) if self._rs else None
    return H(responses)


def _work(authorships):
    return {"id": "https://openalex.org/W1", "publication_year": 2025,
            "authorships": authorships}


def _auth(aid, countries):
    return {"author": {"id": f"https://openalex.org/{aid}"},
            "countries": countries}


def test_works_pool_keeps_only_in_country_qualified():
    http = _fake_http([_fake_resp({"results": [
        _work([_auth("A1", ["GB"]), _auth("O1", ["GB"])]),
        _work([_auth("A1", ["GB"])]),
        _work([_auth("A2", ["US"])]),
    ]})])
    cfg = build_config(argparse.Namespace(no_config=True))
    pool = _openalex_works_pool(cfg, http, ["T1"], "20", "GB", "me@x.org",
                                date.today().year - 5)
    assert "https://openalex.org/A1" in pool
    assert pool["https://openalex.org/A1"]["in_country"] == 2
    assert "https://openalex.org/A2" not in pool   # publishes from the US, not GB


def test_works_pool_field_only_profile():
    http = _fake_http([_fake_resp({"results": [
        _work([_auth("A1", ["DE"])]),
        _work([_auth("A1", ["DE"])]),
    ]})])
    cfg = build_config(argparse.Namespace(no_config=True))
    pool = _openalex_works_pool(cfg, http, [], "27", "DE", "me@x.org",
                                date.today().year - 5)
    assert "https://openalex.org/A1" in pool
    assert pool["https://openalex.org/A1"]["in_country"] == 2


def test_works_pool_no_topics_no_field_returns_empty():
    cfg = build_config(argparse.Namespace(no_config=True))
    assert _openalex_works_pool(cfg, _fake_http([]), [], None, "GB",
                                "me@x.org", 2020) == {}


# ---------------------------------------------------------------------------
# openalex.py — _openalex_author_records (batching stub)
# ---------------------------------------------------------------------------
def test_author_records_batched():
    results = [{"id": "https://openalex.org/A1", "display_name": "Ada"},
               {"id": "https://openalex.org/A2", "display_name": "Bo"}]
    http = _fake_http([_fake_resp({"results": results})])
    recs = _openalex_author_records(http, ["https://openalex.org/A1",
                                           "https://openalex.org/A2"], "me@x.org")
    assert set(recs) == {"https://openalex.org/A1", "https://openalex.org/A2"}
    assert recs["https://openalex.org/A1"]["display_name"] == "Ada"


def test_author_records_failure_returns_empty():
    class H:
        def raw_get(self, url, params=None, **kw):
            class R:
                status_code = 500
                def json(self):
                    return {}
            return R()
    assert _openalex_author_records(H(), ["A1"], "me@x.org") == {}


# ---------------------------------------------------------------------------
# openalex.py — openalex_supervisor_authors (end-to-end with stub HTTP)
# ---------------------------------------------------------------------------
def test_openalex_supervisor_authors_ranks_and_filters():
    def _auth_rec(aid, name, h, inst):
        return {"id": f"https://openalex.org/{aid}", "display_name": name,
                "orcid": f"https://orcid.org/0000-{aid}", "works_count": 50,
                "cited_by_count": 9000, "summary_stats": {"h_index": h},
                "affiliations": [
                    {"institution": {"display_name": inst, "type": "education",
                                     "country_code": "GB"},
                     "years": [2022, 2023, 2024, 2025]}],
                "last_known_institutions": [
                    {"display_name": inst, "country_code": "GB"}],
                "topics": [{"id": "https://openalex.org/T1",
                            "display_name": "Macroeconomics"}]}

    def _recent(owner_id):
        return {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x",
                "title": "Recent macro paper", "publication_year": 2025,
                "authorships": [{"author": {"id": owner_id},
                                 "author_position": "last",
                                 "is_corresponding": True,
                                 "countries": ["GB"],
                                 "institutions": [{"display_name": "LSE",
                                                   "country_code": "GB"}]}],
                "primary_topic": {"field": {"id": "https://openalex.org/fields/20"}}}

    class Http:
        def __init__(self):
            self.calls = []
        def raw_get(self, url, params=None, **kw):
            self.calls.append(url)
            filt = (params or {}).get("filter") or ""
            if filt.startswith("openalex_id:"):
                return _fake_resp({"results": [
                    _auth_rec("A1", "Ada Grace", 40, "LSE"),
                    _auth_rec("A2", "Bo Lin", 20, "Bank of England"),
                ]})
            if filt.startswith("author.id:"):
                aid = filt.split("author.id:")[1].split(",")[0].rstrip("/")
                return _fake_resp({"results": [_recent(aid),
                                               _recent(aid)]})
            if filt.startswith("authorships.countries:"):
                return _fake_resp({"results": [
                    _work([_auth("A1", ["GB"])]),
                    _work([_auth("A1", ["GB"])]),
                ]})
            return None

    cfg = build_config(argparse.Namespace(no_config=True))
    cfg.supervisor_years_back = 5
    rows = openalex_supervisor_authors(cfg, Http(), ["T1"], "United Kingdom",
                                       "20")
    assert rows and rows[0]["name"] == "Ada Grace"
    assert rows[0]["orcid"] == "0000-A1"
    assert rows[0]["institution"] == "LSE"


def test_openalex_supervisor_authors_empty_without_iso2():
    cfg = build_config(argparse.Namespace(no_config=True))
    assert openalex_supervisor_authors(cfg, _fake_http([]), ["T1"],
                                       "Nowhereistan", None) == []


# ---------------------------------------------------------------------------
# openalex.py — _openalex_author_recent (stub HTTP)
# ---------------------------------------------------------------------------
def test_author_recent_flags_last_corr_and_field():
    def _recent():
        return {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x",
                "title": "Macro paper", "publication_year": 2025,
                "authorships": [
                    {"author": {"id": "https://openalex.org/O1"},
                     "author_position": "first", "countries": ["GB"]},
                    {"author": {"id": "https://openalex.org/A1"},
                     "author_position": "last", "is_corresponding": True,
                     "countries": ["GB"],
                     "institutions": [{"display_name": "LSE",
                                       "country_code": "GB"}]}],
                "primary_topic": {"field": {"id": "https://openalex.org/fields/20"}}}
    http = _fake_http([_fake_resp({"results": [_recent()]})])
    cfg = build_config(argparse.Namespace(no_config=True))
    info = _openalex_author_recent(http, cfg, "https://openalex.org/A1", 2020,
                                   "GB", "me@x.org", "20")
    assert info["in_country"] == 1 and info["n_field"] == 1
    assert info["works"][0]["is_last"] and info["works"][0]["is_corr"]


def test_author_recent_no_results():
    http = _fake_http([_fake_resp({"results": []})])
    cfg = build_config(argparse.Namespace(no_config=True))
    info = _openalex_author_recent(http, cfg, "https://openalex.org/A1", 2020,
                                   "GB", "me@x.org", None)
    assert info["works"] == [] and info["in_country"] == 0


def test_canonical_iso2_map_present():
    assert _CANON_TO_ISO2.get("Germany") == "DE"
    assert _CANON_TO_ISO2.get("United States") == "US"
