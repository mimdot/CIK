"""Tests for sources.seed_urls (migration Step 5, Batch C part 2) — seed file
reading, the academicjobsonline seed adapter, and source_seed_urls via a fake
Http. Functions are also re-exported by the monolith; these exercise the
extracted module directly."""

from __future__ import annotations

import argparse
import os
import types

from core.config import build_config
from core.http import Http
import sources.seed_urls as SU

from phd_aggregator import SEED_ADAPTERS

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting",
 "title": "PhD position in interstellar magnetic fields",
 "hiringOrganization": {"@type": "Organization",
                         "name": "Example Institute"},
 "datePosted": "2026-06-15", "validThrough": "2026-09-30"}
</script></head><body></body></html>"""


def _cfg(tmp_path, seed_file=None, **kw):
    cfg = build_config(argparse.Namespace(
        no_config=True, debug=False, phd_only=False, field=None))
    cfg.seed_file = str(seed_file or (tmp_path / "seeds.txt"))
    cfg.seed_bypass_gate = kw.get("seed_bypass_gate", False)
    cfg.seed_discover_siblings = kw.get("seed_discover_siblings", False)
    cfg.seed_max_siblings = kw.get("seed_max_siblings", 5)
    cfg.state_path = str(tmp_path / "state.json")
    return cfg


class _FakeHttp(Http):
    """Http stand-in: serves canned pages per URL, no network."""

    def __init__(self, pages):
        self._pages = pages
        self.cfg = types.SimpleNamespace()

    def fetch_page(self, url):
        return self._pages.get(url)

    def get(self, url):
        return types.SimpleNamespace(text=self._pages.get(url, ""))


def test_read_seed_file_parses_and_dedupes(tmp_path):
    p = tmp_path / "seeds.txt"
    p.write_text("# comment\n"
                 "https://ex.org/a\n"
                 "not a url\n"
                 "https://ex.org/a#frag\n"
                 "https://ex.org/b\n")
    urls = SU._read_seed_file(str(p))
    assert urls == ["https://ex.org/a", "https://ex.org/b"]
    assert SU._read_seed_file(str(tmp_path / "missing.txt")) == []


def test_academicjobsonline_adapter_registered():
    assert "academicjobsonline.org" in SEED_ADAPTERS
    spec = SU._adapt_academicjobsonline("https://academicjobsonline.org/ajo/jobs/1")
    assert spec["listings"]
    assert spec["link_re"].match("/ajo/jobs/123")


def test_source_seed_urls_ingests_and_marks_seed(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "seeds.txt").write_text("https://ex.org/jobs/42\n")
    http = _FakeHttp({"https://ex.org/jobs/42": JSONLD_PAGE})
    recs = SU.source_seed_urls(cfg, http)
    assert len(recs) == 1
    assert recs[0]["_seed"] is True
    assert recs[0]["title"].startswith("PhD position in interstellar")
    assert os.path.exists(cfg.state_path)          # state persisted


def test_source_seed_urls_empty_without_seed_file(tmp_path):
    cfg = _cfg(tmp_path)
    assert SU.source_seed_urls(cfg, _FakeHttp({})) == []


def test_source_seed_urls_discover_siblings(tmp_path):
    cfg = _cfg(tmp_path, seed_discover_siblings=True)
    seed = "https://board.org/jobs/12345/phd-in-astrophysics"
    (tmp_path / "seeds.txt").write_text(seed + "\n")
    listing = ('<html><body>'
               '<a href="https://board.org/jobs/88888/phd-in-cosmology">x</a>'
               '</body></html>')
    http = _FakeHttp({seed: JSONLD_PAGE,
                      "https://board.org/jobs/88888/phd-in-cosmology": JSONLD_PAGE})
    recs = SU.source_seed_urls(cfg, http)
    assert len(recs) >= 1
    assert recs[0]["_seed"] is True
