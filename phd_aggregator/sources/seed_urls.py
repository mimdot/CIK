"""source_seed_urls — hand-picked position links (+ sibling postings on the
same board) (migration Step 5, Batch C, part 2).

Reads SEED_FILE (default ./seeds.txt; one URL per line, '#' comments), pulls
each page through the full anti-bot fetch chain and parses it into the
standard record schema, trying in order:
    (1) schema.org JSON-LD "JobPosting"  (most job pages embed it; reliable)
    (2) OpenGraph / <meta> tags
    (3) readability-style main-text extraction (last resort)
Hand-picked seeds bypass the relevance/type gates when SEED_BYPASS_GATE is
on (they are still scored, classified and deadline/freshness-filtered).
For every seed the source also tries to find the board's parent listing page
and harvest SIBLING postings — those go through the NORMAL filters.

Parse helpers live in pipeline.parse_page; state persistence in
pipeline.freshness.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core.config import Config
from core.deps import _HTML_PARSER
from core.http import Http
from core.utils import normalize_url
from pipeline.freshness import load_state, save_state
from pipeline.parse_page import (SEED_ADAPTERS, _parent_listing_candidates,
                                 _seed_sibling_pattern, parse_position_page,
                                 seed_adapter)

from .base import log, register_source


# SEED URLS — hand-picked position links (+ sibling postings on the same board)
#
# Reads SEED_FILE (default ./seeds.txt; one URL per line, '#' comments), pulls
# each page through the full anti-bot fetch chain and parses it into the
# standard record schema, trying in order:
#     (1) schema.org JSON-LD "JobPosting"  (most job pages embed it; reliable)
#     (2) OpenGraph / <meta> tags
#     (3) readability-style main-text extraction (last resort)
# Hand-picked seeds bypass the relevance/type gates when SEED_BYPASS_GATE is
# on (they are still scored, classified and deadline/freshness-filtered).
# For every seed the source also tries to find the board's parent listing page
# and harvest SIBLING postings — those go through the NORMAL filters.
# -----------------------------------------------------------------------------
def _read_seed_file(path: str) -> list[str]:
    """Seed file format: one URL per line; blank lines and '#'-comments
    (full-line or trailing) are ignored."""
    urls: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line.startswith(("http://", "https://")):
                    urls.append(line)
                elif line:
                    log.warning("[seed_urls] %s: skipping non-URL line %r",
                                path, line[:60])
    except FileNotFoundError:
        log.info("[seed_urls] no seed file at %s — nothing to do "
                 "(create it with one position URL per line)", path)
    except Exception as exc:
        log.warning("[seed_urls] could not read %s: %s", path, exc)
    return list(dict.fromkeys(urls))     # de-dupe, keep order








@seed_adapter("academicjobsonline.org")
def _adapt_academicjobsonline(seed_url: str) -> dict:
    """Fully-worked example adapter: AJO postings live at /ajo/jobs/<id>; the
    astronomy listing pages enumerate them."""
    return {
        "listings": ["https://academicjobsonline.org/ajo/physics/Astronomy",
                     "https://academicjobsonline.org/ajo/physics/Astrophysics"],
        "link_re": re.compile(r"^/ajo/jobs/\d+/?$"),
    }




def discover_siblings(seed_url: str, seed_html: Optional[str], cfg: Config,
                      http: Http, known: set) -> list[dict]:
    """Find sibling postings on the seed's board and parse them into records
    (these go through the NORMAL filters — no gate bypass)."""
    try:
        domain = urlparse(seed_url).netloc.lower()
    except Exception:
        return []
    bare = domain[4:] if domain.startswith("www.") else domain

    link_re = None
    adapter = SEED_ADAPTERS.get(bare)
    if adapter:
        try:
            spec = adapter(seed_url) or {}
        except Exception as exc:
            log.warning("[seed_urls] adapter for %s failed: %s", bare, exc)
            spec = {}
        listings = list(spec.get("listings") or [])
        link_re = spec.get("link_re")
    else:
        soup = None
        if seed_html:
            try:
                soup = BeautifulSoup(seed_html, _HTML_PARSER)
            except Exception:
                pass
        listings = _parent_listing_candidates(seed_url, soup)
    if link_re is None:
        link_re = _seed_sibling_pattern(seed_url)
    if not listings or link_re is None:
        log.info("[seed_urls] %s: no usable parent listing / link pattern — "
                 "add a seed adapter to enable sibling discovery (see "
                 "CONTRIBUTING.md)", seed_url)
        return []

    sibling_urls: list[str] = []
    for listing in listings:
        html = http.fetch_page(listing)
        if not html:
            continue
        try:
            lsoup = BeautifulSoup(html, _HTML_PARSER)
        except Exception:
            continue
        for a in lsoup.find_all("a", href=True):
            u = urljoin(listing, a["href"])
            try:
                pu = urlparse(u)
            except Exception:
                continue
            if pu.netloc.lower() not in (domain, "www." + bare, bare):
                continue
            if not link_re.match(pu.path):
                continue
            k = normalize_url(u)
            if not k or k in known:
                continue
            known.add(k)
            sibling_urls.append(u)
            if len(sibling_urls) >= cfg.seed_max_siblings:
                break
        if sibling_urls:
            break        # first listing page that yields siblings wins

    out: list[dict] = []
    for u in sibling_urls:
        html = http.fetch_page(u)
        rec = parse_position_page(html, u, source="seed_siblings")
        if rec:
            out.append(rec)
    if sibling_urls:
        log.info("[seed_urls] %s: %d sibling posting(s) via %s",
                 bare, len(out), "adapter" if adapter else "generic heuristic")
    return out


@register_source("seed_urls", label="Your seed URLs")
def source_seed_urls(cfg: Config, http: Http) -> list[dict]:
    """[HTML] Hand-picked seed URLs from the seed file (+ board siblings).
    See the section comment above for the parse chain and gate semantics."""
    urls = _read_seed_file(cfg.seed_file)
    if not urls:
        return []
    log.info("[seed_urls] %d seed URL(s) from %s (gate bypass: %s, "
             "sibling discovery: %s)", len(urls), cfg.seed_file,
             cfg.seed_bypass_gate, cfg.seed_discover_siblings)

    state = load_state(cfg)
    domains = state.setdefault("seed_domains", {})
    today_iso = date.today().isoformat()

    out: list[dict] = []
    known: set = {normalize_url(u) for u in urls if normalize_url(u)}
    for url in urls:
        html = http.fetch_page(url)
        rec = parse_position_page(html, url, source="seed_urls")
        if rec:
            rec["_seed"] = True          # gate-bypass marker (internal)
            out.append(rec)
        else:
            log.warning("[seed_urls] could not ingest %s", url)

        # track recurring domains -> candidates for a dedicated source/adapter
        try:
            bare = urlparse(url).netloc.lower()
            bare = bare[4:] if bare.startswith("www.") else bare
        except Exception:
            bare = None
        if bare:
            d = domains.setdefault(bare, {"count": 0, "first_seen": today_iso})
            d["count"] += 1
            d["last_seen"] = today_iso
            if d["count"] >= 3 and bare not in SEED_ADAPTERS:
                log.info("[seed_urls] domain %s has appeared %d times — "
                         "consider a seed adapter or a dedicated "
                         "@register_source (see CONTRIBUTING.md)",
                         bare, d["count"])

        if cfg.seed_discover_siblings and html:
            try:
                out.extend(discover_siblings(url, html, cfg, http, known))
            except Exception as exc:
                log.warning("[seed_urls] sibling discovery failed for %s: %s",
                            url, exc)

    save_state(state, cfg)
    return out
