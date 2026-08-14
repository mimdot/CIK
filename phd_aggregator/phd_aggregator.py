#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phd_aggregator.py — aggregate open PhD positions in astronomy/astrophysics
=========================================================================

Pulls listings from academic job sources, scores them against a tiered
astronomy taxonomy (core anchors / context boosters / negative terms),
filters by position type (PhD by default, postdoc/faculty excluded),
deduplicates across sources, flags NEW entries since the previous run, and
writes CSV + JSON + a self-contained results.html dashboard.

Design goals: one self-contained function per source (toggle independently,
add new ones in ~5 lines), defensive parsing (every field may be missing),
polite/robust HTTP (robots.txt, rate limiting, retries+backoff, proxy), and
easy reconfiguration for other career levels or fields via the CONFIG block.

------------------------------------------------------------------------------
INSTALL (minimal deps):
    pip install requests beautifulsoup4 feedparser
    pip install "requests[socks]"    # required if PROXY is a socks5:// URL
    pip install pyyaml               # optional, enables config.yaml + fields/*.yaml
    pip install lxml                 # optional, faster/robuster HTML parsing
    pip install curl_cffi            # optional, browser-TLS fallback for 403s
    pip install readability-lxml     # optional, better seed-page text extraction
    pip install playwright && playwright install chromium   # optional, only
                                                            # for JS sources

RUN:
    python phd_aggregator.py                 # config.yaml + CONFIG block below
    python phd_aggregator.py --self-test     # offline test of the pipeline
    python phd_aggregator.py --list-sources  # show registered sources + status
    python phd_aggregator.py --list-fields   # show installed field profiles
    python phd_aggregator.py --new-field my_major   # scaffold YOUR field profile
    python phd_aggregator.py --source euraxess --source nature_careers
    python phd_aggregator.py --country Germany --country Japan
    python phd_aggregator.py --field astronomy       # field profile (fields/*.yaml)
    python phd_aggregator.py --find-supervisors --field ism --country Germany
                                             # rank likely PhD supervisors
                                             # (OpenAlex: any major, no token /
                                             # ADS for astro+physics / arXiv)
    python phd_aggregator.py --seeds seeds.txt       # hand-picked position URLs
    python phd_aggregator.py --proxy ""      # disable the proxy entirely
    python phd_aggregator.py --extras        # + emails, professors, scholarships
    python phd_aggregator.py --no-fetch --write-emails   # emails from last run
    python phd_aggregator.py --no-fetch --find-professors --scholarships

CONFIG lives in three layers (later beats earlier): the CONFIG block below ->
config.yaml (runtime settings) -> fields/<profile>.yaml (field taxonomy;
--field selects) -> CLI flags. Secrets (ADS token) come from the environment
or a gitignored .env; personal data for --write-emails from applicant.yaml.

CAREER TOOLKIT (profile from gitignored applicant.yaml — see APPLICANT_PROFILE):
    --write-emails     one tailored application email per found position
                       -> ./emails/NNN_institution_title.txt (+ _index.csv)
    --find-professors  curated + live-arXiv list of researchers in your fields
                       -> professors.md / professors.csv
    --scholarships     funding programs matched to your profile & regions
                       -> scholarships.md / scholarships.csv
    The uni_departments source also writes <output>_universities.csv — the
    full registry of top physics/astronomy departments it sweeps.

------------------------------------------------------------------------------
ACCESS FROM IRAN (V2RayN / xray):
    * PROXY defaults to socks5h://127.0.0.1:10808  (V2RayN local SOCKS inbound;
      the 'h' means DNS is resolved through the proxy, so poisoned local DNS
      can't break lookups). The HTTP inbound variant is "http://127.0.0.1:10809"
      if you have it enabled in V2RayN.
    * If V2Ray runs in system-wide TUN mode the SOCKS port may be closed; with
      PROXY_FALLBACK_DIRECT=True the script detects this and continues without
      the explicit proxy (traffic still exits through the tunnel).
    * ALL traffic goes through the proxy: requests, curl_cffi, and the headless
      browser (Chromium is launched with the proxy + remote-DNS resolver flags).
    * The proxy fixes GEO blocks but not ANTI-BOT walls. For Cloudflare-guarded
      pages the fetch chain is: plain requests with realistic browser headers
      -> curl_cffi with browser TLS fingerprint -> headless Chrome ->
      (optionally) a visible Chrome window if a display is present. No CAPTCHA
      solving, no ban evasion: if a site still refuses, it is skipped with a
      clear log line. NOTE: some VPN exit IPs have such a bad reputation that
      Cloudflare blocks even a real browser (AAS/FindAPhD do this on some
      exits) — switching the V2Ray server usually fixes it.

------------------------------------------------------------------------------
SOURCE STATUS LEGEND (see each function for details):
    [FEED]   official RSS/Atom or simple API  -> requests + feedparser
    [HTML]   server-rendered HTML             -> requests + BeautifulSoup
    [JS]     JavaScript-rendered              -> needs Playwright
    [STUB]   intentionally not implemented     (ToS / endpoint gone);
             disabled by default, with notes on how to extend it.

Endpoint URLs and CSS selectors for [HTML]/[JS] sources DO drift over time —
each lives in a clearly marked constant so you can fix it in one place. A
source that breaks logs a warning and is skipped — it never crashes the run.
All endpoints below were verified live in July 2026.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import socket
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional
from urllib.parse import quote, urlencode, urljoin, urlparse, urlunparse, parse_qsl
from urllib.robotparser import RobotFileParser

# --- required third-party deps (fail early with a helpful message) -----------
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover - environment guard
    sys.stderr.write(
        "Missing dependency: %s\n"
        "Install with:\n"
        "    pip install requests beautifulsoup4 feedparser\n" % exc
    )
    raise

# pandas is NO LONGER REQUIRED. CSV writing moved to core.csvout (stdlib), so
# pandas + numpy — 103 MB of the desktop bundle — is now only an optional
# nicety for one date-parsing fallback in core.utils. Imported lazily there.


from core.deps import _HAVE_CURL_CFFI, _HAVE_PLAYWRIGHT, _HTML_PARSER, curl_requests, feedparser  # noqa: F401
from core.config import Config, apply_field_profile, build_config, list_field_profiles, load_field_profile, resolve_field_arg, ADS_API_URL, ADS_TOKEN_ENV, AUTO_DETECT_PROXY, CHALLENGE_WAIT_MS, CONTEXT_TERMS, CORE_ANCHORS, CURL_IMPERSONATION, FIELD_PROFILE, FIELDS_DIR, ISO2_COUNTRY, MAX_AGE_DAYS, MAX_DESC_CHARS, NEGATIVE_TERMS, OPENALEX_API, OPENALEX_AUTHORS_API, OPENALEX_MAILTO, PROBE_TIMEOUT, PROBE_URL, PROXY_CANDIDATES, RELEVANCE_THRESHOLD, RELEVANCE_WEIGHTS, SEED_FILE, SUPERVISOR_COUNTRY_BOOST, SUPERVISOR_MAX_AUTHORS, SUPERVISOR_MAX_PAPERS, SUPERVISOR_MIN_PAPERS, SUPERVISOR_ORCID_EMAILS, SUPERVISOR_RECENCY_WEIGHT, SUPERVISOR_SENIOR_WEIGHT, SUPERVISOR_SOURCE, SUPERVISOR_YEARS_BACK
from core.config import apply_config_yaml, BACKOFF_FACTOR, BROWSER_PROFILE_DIR, CONFIG_FILE, CONNECT_TIMEOUT, COUNTRIES, COUNTRY_ALIASES, CURL_IMPERSONATION_FALLBACK, EXCLUDE_EXPIRED, HEADED_FALLBACK, KEEP_AMBIGUOUS, KEEP_UNDATED_WITHIN_WINDOW, MAX_PAGE_DATE_PROBES, MAX_RETRIES, OUTPUT_PATH, PROXY, PROXY_FALLBACK_DIRECT, REQUEST_DELAY, REQUEST_TIMEOUT, ROBOTS_OBEY, SEARCH_TERMS, SEED_BYPASS_GATE, SEED_DISCOVER_SIBLINGS, SEED_MAX_SIBLINGS, SOURCES_ENABLED, STATE_FILE, SUBFIELDS, SUPERVISOR_ADS_DB, SUPERVISOR_ARXIV_CAT, SUPERVISOR_AUTHOR_ENRICH, SUPERVISOR_AUTHOR_PER_PAGE, SUPERVISOR_MIN_FIELD_SHARE, SUPERVISOR_MIN_IN_COUNTRY_SHARE, SUPERVISOR_POOL_PAGES, SUPERVISOR_RECENT_WORKS, SUPERVISOR_SENIOR_SIGNAL, USER_AGENT, WANTED_POSITION_TYPES, WRITE_HTML
from core.config import _compile_term, _find_config_path, _load_yaml_file, _oa_field_id, _CANON_TO_ISO2, _HAVE_YAML  # noqa: F401
from core.utils import CITY_HINTS, canonical_country, clean_oneline, clean_text, dedupe_key, guess_country, normalize_url, parse_date
from core.records import OUTPUT_FIELDS, make_record
from core.taxonomy import classify_position_type, compile_taxonomy, country_allowed, is_relevant, score_relevance
from core.http import BROWSER_HEADERS, Http, RobotsCache
log = logging.getLogger("phd_aggregator")
from sources.base import SOURCES, log, register_source
from sources import source_aas, source_academicjobsonline, source_academictransfer, source_esa, source_eso, source_euraxess, source_findaphd, source_jrecin, source_jobs_ac_uk, source_linkedin, source_nature_careers, source_uni_departments
from sources import source_astrobetter, source_iau
from sources import LINKEDIN_GUEST_URL, LINKEDIN_KEYWORDS, LINKEDIN_LOCATIONS, LINKEDIN_MAX_PAGES
from sources import UNIVERSITY_DEPARTMENTS
from sources import discover_siblings, source_seed_urls

from pipeline.parse_page import (SEED_ADAPTERS, extract_main_text, extract_page_date, parse_position_page, seed_adapter)
from pipeline.freshness import apply_freshness, load_state, save_state
from pipeline.filter import filter_records

from pipeline.dedupe import dedupe_records
from pipeline.run import (apply_profile_matching, load_previous_keys, mark_new, print_summary, run, sort_key, write_html, write_outputs)

from supervisors import (ARXIV_API, AUTHOR_SEARCH_FMT, SOURCE_LABELS,  # noqa: F401
                         _load_dotenv, _supervisor_chain,
                         _supervisor_focus, ads_supervisor_docs,
                         aggregate_supervisors, arxiv_supervisor_docs,
                         find_supervisors, openalex_supervisor_authors,
                         openalex_supervisor_docs, write_supervisors_html)

from toolkit import (APPLICANT_PROFILE,  # noqa: F401
                     SCHOLARSHIPS,
                     PROFESSOR_SEED, build_email,
                     find_professors, write_emails, write_scholarships)

from selftest import _sample_records, self_test  # noqa: F401

from matching import (  # noqa: F401
    LOCATION_WEIGHT, METHOD_WEIGHT, NEUTRAL, TOPIC_WEIGHT, MatchResult,
    explain_match, location_score,
    method_score, score_match, topic_score,
)

from cli.commands import (  # noqa: F401
    DEFAULT_DB_URL, build_profile_cmd, db_available, load_active_profile,
    make_admin_cmd, seed_db_cmd, show_profile_cmd, sync_supervisors_cmd,
)







# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Aggregate open PhD positions in astronomy/astrophysics.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--list-sources", action="store_true",
                    help="list registered sources and their enabled/JS status, then exit")
    ap.add_argument("--list-fields", action="store_true",
                    help="list available field profiles (fields/*.yaml) and exit")
    ap.add_argument("--new-field", nargs="?", const="", metavar="NAME",
                    help="interactively scaffold a NEW field profile "
                         "(fields/NAME.yaml) for your major and exit")
    ap.add_argument("--source", action="append", metavar="NAME",
                    help="run ONLY this source (repeatable); overrides SOURCES_ENABLED")
    ap.add_argument("--country", action="append", metavar="NAME",
                    help="override region filter (repeatable; use '*' for worldwide)")
    ap.add_argument("--field", metavar="NAME",
                    help="field profile (fields/<NAME>.yaml, default "
                         f"'{FIELD_PROFILE}') OR a subfield of it "
                         "(e.g. 'ism' for --find-supervisors)")
    ap.add_argument("--find-supervisors", action="store_true",
                    help="rank potential PhD supervisors for --field/--country "
                         "from OpenAlex (any major, no token), NASA ADS "
                         "(astro/physics, ADS_API_TOKEN) or arXiv; writes "
                         "supervisors_<field>_<country>.csv/.json and exits")
    ap.add_argument("--sync-supervisors", action="store_true",
                    help="aggregate supervisor candidates across ALL field "
                         "profiles for the given --country (repeatable) and "
                         "upsert into the DB for the dashboard; requires "
                         "--country (e.g. --country Germany --country Netherlands)")
    ap.add_argument("--supervisor-source", choices=["auto", "openalex", "ads",
                                                    "arxiv"],
                    help="literature source for --find-supervisors: 'auto' "
                         "uses ADS for astronomy/physics and OpenAlex for "
                         "every other major (default); 'openalex' covers ANY "
                         "field with no token; 'ads'/'arxiv' force those "
                         f"specific sources (default {SUPERVISOR_SOURCE})")
    ap.add_argument("--years-back", type=int, metavar="N",
                    help="publication window for --find-supervisors "
                         f"(default {SUPERVISOR_YEARS_BACK})")
    ap.add_argument("--seeds", metavar="PATH",
                    help=f"seed-URL file for the seed_urls source "
                         f"(default {SEED_FILE})")
    ap.add_argument("--max-age-days", type=int, metavar="N",
                    help="freshness window: drop posts with no future deadline "
                         f"older than this (default {MAX_AGE_DAYS})")
    ap.add_argument("--no-config", action="store_true",
                    help="ignore config.yaml (use built-in defaults + CLI only)")
    ap.add_argument("--force-refresh", action="store_true",
                    help="bypass the HTTP cache: re-fetch every page instead of "
                         "revalidating with If-None-Match/If-Modified-Since "
                         "(the cache is still refreshed for next time)")
    ap.add_argument("--no-http-cache", action="store_true",
                    help="disable the persistent HTTP conditional-GET cache")
    ap.add_argument("--type", dest="types", action="append", metavar="TYPE",
                    help="which kind of position to hunt: phd or postdoc "
                         "(repeatable). PhD and postdoc are separate searches "
                         "with their own results; omit for the config default")
    ap.add_argument("--include-slow-sources", action="store_true",
                    help="also run the opt-in slow sources (the university "
                         "department sweep: ~150 pages for astronomy, ~20 for "
                         "most fields, one every 2s). Finds openings the job "
                         "boards miss, but adds MINUTES to a run")
    ap.add_argument("--keyword", action="append", metavar="KW",
                    help="EXTRA core anchor terms (repeatable)")
    ap.add_argument("--threshold", type=float, metavar="X",
                    help="override RELEVANCE_THRESHOLD")
    ap.add_argument("--output", metavar="PATH", help="override OUTPUT_PATH base")
    ap.add_argument("--proxy", metavar="URL",
                    help="override PROXY (empty string disables it)")
    ap.add_argument("--no-proxy-detect", action="store_true",
                    help="disable auto-detection: use the configured proxy or "
                         "direct only (no local-port sweep)")
    ap.add_argument("--limit-per-source", type=int, metavar="N",
                    help="cap raw records per source (handy for quick test runs)")
    ap.add_argument("--no-robots", action="store_true",
                    help="do NOT consult robots.txt (use responsibly)")
    ap.add_argument("--no-html", action="store_true",
                    help="skip writing the results.html dashboard")
    ap.add_argument("--no-headed", action="store_true",
                    help="never open a visible browser window as anti-bot fallback")
    ap.add_argument("--include-expired", action="store_true",
                    help="keep positions whose deadline has passed")
    ap.add_argument("--phd-only", action="store_true",
                    help="strict mode: drop positions whose level cannot be "
                         "verified as a PhD (overrides keep_ambiguous)")
    ap.add_argument("--browser-profile", metavar="DIR",
                    help="persistent browser profile directory (cookies survive "
                         "between runs so Cloudflare stops challenging you)")
    ap.add_argument("--fresh-profile", action="store_true",
                    help="wipe the persistent browser profile before starting")
    ap.add_argument("--challenge-wait", metavar="MS", type=int,
                    help="ms to wait for an anti-bot challenge to auto-clear "
                         f"(default {CHALLENGE_WAIT_MS})")
    ap.add_argument("--write-emails", action="store_true",
                    help="write one customized application email per position "
                         "into ./emails/ (uses APPLICANT_PROFILE)")
    ap.add_argument("--find-professors", action="store_true",
                    help="write professors.csv/.md: researchers in your fields "
                         "(curated + live arXiv survey)")
    ap.add_argument("--scholarships", action="store_true",
                    help="write scholarships.md/.csv matched to your profile")
    ap.add_argument("--extras", action="store_true",
                    help="shorthand for --write-emails --find-professors --scholarships")
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip scraping the job boards; reuse the existing "
                         "output JSON (for --write-emails etc.)")
    ap.add_argument("--self-test", action="store_true",
                    help="run the offline pipeline self-test and exit")
    ap.add_argument("--db", metavar="URL",
                    help=f"SQLAlchemy database URL for profiles/opportunities "
                         f"(default {DEFAULT_DB_URL})")
    ap.add_argument("--build-profile", metavar="\"CV TEXT\"",
                    help="extract a UserProfile from CV/bio text via LLM, save "
                         "it as the active profile in --db, and print it")
    ap.add_argument("--seed-db", metavar="PATH",
                    help="seed the opportunities table from the pipeline's "
                         "JSON output (e.g. phd_positions.json) and print the "
                         "record count")
    ap.add_argument("--show-profile", action="store_true",
                    help="print the active profile stored in --db")
    ap.add_argument("--make-admin", metavar="EMAIL",
                    help="promote EMAIL to the admin role (bootstrap the first "
                         "admin who creates invite codes) and exit")
    ap.add_argument("--debug", action="store_true", help="verbose logging + tracebacks")
    return ap.parse_args(argv)


def do_list_sources(cfg: Config) -> None:
    print("Registered sources (enabled per current config):")
    for name in SOURCES:
        status = "on " if cfg.sources_enabled.get(name, False) else "off"
        doc = (SOURCES[name].__doc__ or "").strip().splitlines()
        tag = ""
        if doc:
            m = re.search(r"\[(FEED|HTML|JS|STUB|HTML/JS|FEED/HTML|FEED/JS)\]", doc[0])
            tag = m.group(0) if m else ""
        print(f"  [{status}] {name:<20} {tag}")
    print(f"\nPlaywright: {_HAVE_PLAYWRIGHT}  |  curl_cffi: {_HAVE_CURL_CFFI}"
          f"  |  HTML parser: {_HTML_PARSER}")


def new_field_wizard(name: str) -> int:
    """Interactively scaffold a new fields/<name>.yaml for YOUR major."""
    name = name.strip().lower().replace(" ", "_").replace("-", "_")
    if not re.fullmatch(r"[a-z0-9_]+", name or ""):
        print("Please pass a profile name:  --new-field marine_biology")
        return 2
    out = os.path.join(FIELDS_DIR, f"{name}.yaml")
    if os.path.exists(out):
        print(f"fields/{name}.yaml already exists — use --field {name} instead, "
              "or delete the file first.")
        return 2
    print(f"Scaffolding a new field profile: fields/{name}.yaml")
    print("(type each term and press Enter; a BLANK line finishes a list)\n")

    def ask_list(prompt: str, hint: str) -> list[str]:
        print(f"-- {prompt}\n   ({hint})")
        items: list[str] = []
        while True:
            try:
                line = input("   > ").strip()
            except EOFError:
                break
            if not line:
                break
            for piece in re.split(r"[;,]", line):
                piece = piece.strip()
                if piece and piece not in items:
                    items.append(piece)
        return items

    try:
        description = input("Short description of this major (one line): ").strip()
    except EOFError:
        description = ""
    core = ask_list(
        "CORE anchors — a posting MUST match at least one of these",
        "use PREFIX forms so one term catches many words, e.g. 'molecul' matches "
        "molecular/molecule; one term per line")
    if not core:
        print("Need at least one core anchor — aborting.")
        return 1
    context = ask_list(
        "CONTEXT terms — boost score, never qualify alone",
        "methods/adjacent topics, e.g. 'simulation', 'machine learning'")
    negative = ask_list(
        "NEGATIVE terms — other fields to demote",
        "e.g. 'astrophysic', 'organic chemistry'")
    search = ask_list(
        "SEARCH terms — typed into each job board's own search box",
        "plain keywords like 'cancer biology', 'genomics'")
    if not search:
        search = core[:8]
    try:
        threshold = float(input("Relevance threshold (2.0 = default; raise for stricter): ").strip())
    except (ValueError, EOFError):
        threshold = 2.0

    lines = [
        f"# fields/{name}.yaml — your new field profile (generated with "
        f"--new-field)",
        "# =============================================================================",
        "# Select at runtime with:  python phd_aggregator.py --field " + name,
        "#",
        "# Matching rules (see the relevance engine in phd_aggregator.py):",
        "#   * lowercase terms match case-insensitively as PREFIXES",
        '#     ("molecul" catches molecular/molecule/molecularly);',
        "#   * ALL-CAPS terms (<= 6 chars) match as case-SENSITIVE whole words.",
        "#",
        "#   core_anchors   a post MUST match >= 1 of these to qualify at all",
        "#   context_terms  boost the score but can never qualify a post alone",
        "#   negative_terms demote a post (ignored when a core anchor is in the title)",
        "#   search_terms   typed into each job board's own search box (coverage)",
        "#   weights/threshold  the scoring rule: keep iff >=1 anchor AND score >= threshold",
        "#   departments    (OPTIONAL) university pages the uni_departments source",
        "#                  sweeps for openings: {country, institution, url}.",
        "#                  Left out = falls back to the built-in astronomy registry;",
        "#                  use `departments: []` to disable that source.",
        "# =============================================================================",
        f"name: {name}",
        f"description: {description or name}",
        "core_anchors:",
        *[f"- {a}" for a in core],
        "context_terms:",
        *[f"- {a}" for a in context],
        "negative_terms:",
        *[f"- {a}" for a in negative],
        "search_terms:",
        *[f"- {a}" for a in search],
        "weights:",
        "  core_title: 5.0",
        "  core_desc: 2.5",
        "  context_title: 1.0",
        "  context_desc: 0.5",
        "  negative: -2.0",
        f"threshold: {threshold:g}",
        "# subfields: (for --find-supervisors --field <subfield>)",
        "#   example_subfield:",
        "#     label: Human-readable subfield name",
        "#     keywords: [word1, word2, ...]",
    ]
    if _HAVE_YAML:
        os.makedirs(FIELDS_DIR, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("PyYAML not installed — profile written as fields/%s.txt" % name)
        out = os.path.join(FIELDS_DIR, f"{name}.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return 1
    print(f"\nWrote {out}")
    print(f"Run:  python phd_aggregator.py --field {name}")
    print(f"Re-run this wizard anytime for a new major:  "
          f"python phd_aggregator.py --new-field another_major")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    _load_dotenv()          # gitignored .env -> os.environ (ADS_API_TOKEN etc.)
    cfg = build_config(args)

    if args.list_sources:
        do_list_sources(cfg)
        return 0
    if args.list_fields:
        names = list_field_profiles()
        print(f"Available field profiles ({len(names)}):")
        for n in names:
            prof = load_field_profile(n) or {}
            ndeps = len(prof.get("departments") or [])
            print(f"  {n:<24} {prof.get('description', '')[:70] or '(no description)'}"
                  + (f"  [{ndeps} departments]" if ndeps else ""))
        if cfg.field_profile not in names:
            print(f"\nActive profile '{cfg.field_profile}' has no fields/{cfg.field_profile}.yaml"
                  " (built-in astronomy taxonomy used).")
        return 0
    if args.new_field is not None:
        return new_field_wizard(args.new_field)
    if args.self_test:
        return self_test(cfg)
    if args.find_supervisors:
        return find_supervisors(cfg, Http(cfg))
    if args.sync_supervisors:
        return sync_supervisors_cmd(args.country, field=args.field, db_url=args.db or DEFAULT_DB_URL)
    if args.build_profile:
        return build_profile_cmd(args.build_profile, db_url=args.db or DEFAULT_DB_URL)
    if args.seed_db:
        return seed_db_cmd(args.seed_db, db_url=args.db or DEFAULT_DB_URL)
    if args.show_profile:
        return show_profile_cmd(db_url=args.db or DEFAULT_DB_URL)
    if args.make_admin:
        return make_admin_cmd(args.make_admin,
                              db_url=args.db or DEFAULT_DB_URL)

    # Track C3: if a profile exists in the DB, --run scores every kept
    # opportunity against it and the outputs carry match_score/explanation.
    profile = load_active_profile(args.db or DEFAULT_DB_URL)
    if profile is not None:
        log.info("active profile loaded from %s (domain=%s)",
                 args.db or DEFAULT_DB_URL, profile.domain)

    if cfg.proxy:
        log.info("using proxy: %s (all traffic, incl. headless browser)", cfg.proxy)
    log.info("anchors=%d context=%d negatives=%d threshold=%.1f | countries=%s | types=%s",
             len(cfg.core_anchors), len(cfg.context_terms),
             len(cfg.negative_terms), cfg.threshold, cfg.countries,
             cfg.wanted_types)

    do_emails = args.write_emails or args.extras
    do_professors = args.find_professors or args.extras
    do_scholarships = args.scholarships or args.extras

    if args.no_fetch:
        records: list[dict] = []
        if os.path.exists(cfg.json_path):
            try:
                with open(cfg.json_path, "r", encoding="utf-8") as fh:
                    records = json.load(fh)
                log.info("--no-fetch: reusing %d records from %s",
                         len(records), cfg.json_path)
            except Exception as exc:
                log.error("--no-fetch: could not read %s: %s", cfg.json_path, exc)
        else:
            log.error("--no-fetch: %s not found — run once without --no-fetch",
                      cfg.json_path)
    else:
        records = run(cfg, only_sources=args.source,
                      limit_per_source=args.limit_per_source,
                      profile=profile)

    if profile and records:
        # --no-fetch path: reuse the previous run's records but still score
        # them against the active profile (same deterministic engine), then
        # persist the scored version back to the output files (Track C3).
        apply_profile_matching(records, profile, cfg)
        if args.no_fetch:
            write_outputs(records, cfg)

    if do_emails:
        write_emails(records, cfg)
    if do_professors:
        # arXiv survey needs the network even under --no-fetch; failures are soft
        find_professors(cfg, http=Http(cfg))
    if do_scholarships:
        write_scholarships(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
