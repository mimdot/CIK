"""Tests for pipeline.parse_page (migration Step 6) — position-page parsing,
the SEED_ADAPTERS registry/decorator, the sibling finder helpers, and
extract_page_date. All functions are also re-exported by the monolith; these
tests exercise the extracted module directly."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

import pipeline.parse_page as PP

from core.deps import _HTML_PARSER

JSONLD_FIXTURE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting",
 "title": "PhD position in interstellar magnetic fields (f/m/d)",
 "hiringOrganization": {"@type": "Organization",
                         "name": "Example Institute for Astrophysics"},
 "jobLocation": {"@type": "Place",
   "address": {"@type": "PostalAddress", "addressLocality": "Bonn",
               "addressCountry": "DE"}},
 "datePosted": "2026-06-15", "validThrough": "2026-09-30T23:59",
 "description": "<p>Doctoral project on <b>Faraday rotation</b> and the interstellar medium of nearby galaxies.</p>"}
</script></head>
<body><main>Apply by the deadline. Posted on 15 June 2026.</main></body>
</html>"""


def test_parse_position_page_jsonld_beats_og():
    rec = PP.parse_position_page(JSONLD_FIXTURE, "https://ex.org/jobs/42",
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
    rec = PP.parse_position_page(html, "https://ex.org/jobs/43")
    assert rec is not None
    assert rec["title"] == "PhD studentship in cosmology"
    assert rec["deadline"] == "2099-08-15"


def test_parse_position_page_rejects_untitled():
    assert PP.parse_position_page("<html><body><p>nothing here</p></body></html>",
                                  "https://ex.org/x") is None
    assert PP.parse_position_page("", "https://ex.org/x") is None


def test_iter_jsonld_flattens_lists_and_graph():
    html = """<script type="application/ld+json">
    [{"@type": "JobPosting", "@graph": [{"@type": "Person", "name": "Ada"}]},
     {"@type": "JobPosting", "name": "Second"}]
    </script>"""
    soup = BeautifulSoup(html, _HTML_PARSER)
    nodes = list(PP._iter_jsonld_objects(soup))
    assert any(n.get("name") == "Ada" for n in nodes)
    assert any(n.get("name") == "Second" for n in nodes)


def test_jsonld_location_flattens_postal_address():
    node = {"jobLocation": {"address": {"addressLocality": "Bonn",
                                        "addressCountry": "DE"}}}
    assert PP._jsonld_location(node) == "Bonn, DE"


def test_extract_page_date_sources():
    html = "<html><body><p>Position posted on 12 June 2026.</p></body></html>"
    assert PP.extract_page_date(html) == "2026-06-12"
    assert PP.extract_page_date("<html></html>") is None


def test_seed_adapter_registry():
    PP.SEED_ADAPTERS.pop("example.org", None)
    assert "example.org" not in PP.SEED_ADAPTERS

    @PP.seed_adapter("www.example.org")
    def _adapter(seed_url):
        return {"listings": ["https://example.org/listings"],
                "link_re": re.compile(r"^/pos/\d+/?$")}

    assert "example.org" in PP.SEED_ADAPTERS
    assert PP.SEED_ADAPTERS["example.org"] is _adapter
    PP.SEED_ADAPTERS.pop("example.org", None)


def test_seed_sibling_pattern():
    pat = PP._seed_sibling_pattern(
        "https://board.org/jobs/12345/phd-in-astrophysics")
    assert pat is not None
    assert pat.match("/jobs/99999/phd-in-cosmology")
    assert not pat.match("/jobs/abc/phd-in-cosmology")
    assert PP._seed_sibling_pattern("https://board.org/index.html") is None


def test_parent_listing_candidates():
    html = ('<a href="https://board.org/results">back to results</a>')
    soup = BeautifulSoup(html, _HTML_PARSER)
    cands = PP._parent_listing_candidates("https://board.org/jobs/42/x", soup)
    assert cands[0] == "https://board.org/results"
    assert any("board.org/jobs" in c for c in cands)
