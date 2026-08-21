"""core.config — configuration subsystem of astra.py (migration Step 1).

Extracted verbatim from ``astra/astra.py`` during the module
refactor (see MIGRATION_PLAN.md). This module owns:

* the CONFIG block of constants (relevance taxonomy, sources, proxy, seed URLs,
  freshness, supervisor finder, anti-bot tuning...),
* the :class:`Config` dataclass,
* the config.yaml + fields/*.yaml plumbing (``_load_yaml_file``,
  ``apply_config_yaml``, ``apply_field_profile``, ``resolve_field_arg``),
* ``build_config()`` — the single entry point the CLI and tests use,
* the country/ISO2 alias tables that ``apply_config_yaml`` extends, and
* ``compile_taxonomy()`` (the tiny regex compilation ``build_config`` ends with).

The monolith re-imports every public name from here, so ``astra.py``
and any importer of it (e.g. test_supervisors.py) keep working unchanged.

Relocation notes vs. the original monolith code:
* ``_script_dir()`` returns the PARENT of this file (``core/`` sits one level
  under the aggregator dir), so config.yaml / fields/*.yaml / .env resolution
  is unchanged.
* ``compile_taxonomy``/``_compile_term`` and the country alias tables travel
  with the config code because ``build_config``/``apply_config_yaml`` need them;
  Step 3 of the migration re-homes them to ``core/taxonomy.py``.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("astra")

# PyYAML enables the external config.yaml + fields/*.yaml profiles. Without it
# the built-in astronomy defaults below are used (a clear log line says so).
try:
    import yaml  # type: ignore
    _HAVE_YAML = True
except ImportError:
    yaml = None
    _HAVE_YAML = False

# Names the monolith re-imports wholesale via `from core.config import *`.
__all__ = [
    # objects / functions
    "Config", "apply_config_yaml", "apply_field_profile", "build_config",
    "list_field_profiles", "load_field_profile", "resolve_field_arg",
    # constants (CONFIG block + country tables)
    "ADS_API_URL", "ADS_TOKEN_ENV", "AUTO_DETECT_PROXY", "BACKOFF_FACTOR",
    "BROWSER_PROFILE_DIR", "CHALLENGE_WAIT_MS", "CONFIG_FILE",
    "CONNECT_TIMEOUT", "CONTEXT_TERMS", "CORE_ANCHORS", "COUNTRIES",
    "COUNTRY_ALIASES", "CURL_IMPERSONATION", "CURL_IMPERSONATION_FALLBACK",
    "EXCLUDE_EXPIRED", "FIELD_PROFILE", "FIELDS_DIR", "HEADED_FALLBACK",
    "ISO2_COUNTRY", "KEEP_AMBIGUOUS", "KEEP_UNDATED_WITHIN_WINDOW",
    "MAX_AGE_DAYS", "MAX_DESC_CHARS", "MAX_PAGE_DATE_PROBES", "MAX_RETRIES",
    "NEGATIVE_TERMS", "OPENALEX_API", "OPENALEX_AUTHORS_API",
    "OPENALEX_MAILTO", "OUTPUT_PATH", "PROBE_TIMEOUT", "PROBE_URL", "PROXY",
    "PROXY_CANDIDATES", "PROXY_FALLBACK_DIRECT", "RELEVANCE_THRESHOLD",
    "RELEVANCE_WEIGHTS", "REQUEST_DELAY", "REQUEST_TIMEOUT", "ROBOTS_OBEY",
    "SEARCH_TERMS", "SEED_BYPASS_GATE", "SEED_DISCOVER_SIBLINGS", "SEED_FILE",
    "SEED_MAX_SIBLINGS", "SOURCES_ENABLED", "STATE_FILE", "SUBFIELDS",
    "SUPERVISOR_ADS_DB", "SUPERVISOR_ARXIV_CAT", "SUPERVISOR_AUTHOR_ENRICH",
    "SUPERVISOR_AUTHOR_PER_PAGE", "SUPERVISOR_COUNTRY_BOOST",
    "SUPERVISOR_MAX_AUTHORS", "SUPERVISOR_MAX_PAPERS",
    "SUPERVISOR_MIN_FIELD_SHARE", "SUPERVISOR_MIN_IN_COUNTRY_SHARE",
    "SUPERVISOR_MIN_PAPERS", "SUPERVISOR_ORCID_EMAILS", "SUPERVISOR_POOL_PAGES",
    "SUPERVISOR_RECENCY_WEIGHT", "SUPERVISOR_RECENT_WORKS",
    "SUPERVISOR_SENIOR_SIGNAL", "SUPERVISOR_SENIOR_WEIGHT",
    "SUPERVISOR_SOURCE", "SUPERVISOR_YEARS_BACK", "USER_AGENT",
    "WANTED_POSITION_TYPES", "WRITE_HTML",
]


# =============================================================================
# CONFIG  —  edit this block.  Everything below it is machinery.
# =============================================================================

# -----------------------------------------------------------------------------
# RELEVANCE TAXONOMY (three tiers — this replaces the old flat KEYWORDS list)
#
#   CORE_ANCHORS    a post MUST match at least one of these to qualify at all.
#                   Matching is case-insensitive prefix ("astrophysic" catches
#                   astrophysics/astrophysical/astrophysicist), except ALL-CAPS
#                   terms which match as case-SENSITIVE whole words (so "ISM"
#                   doesn't fire inside "mechanism" and "ALMA" not in "alma
#                   mater"). Internal spaces/hyphens are interchangeable
#                   ("gamma-ray burst" == "gamma ray burst").
#   CONTEXT_TERMS   boost the score but can NEVER qualify a post on their own
#                   (this was the old bug: "theoretical"/"magnetism" alone let
#                   quantum-optics and condensed-matter posts through).
#   NEGATIVE_TERMS  demote a post; ignored entirely when a core anchor appears
#                   in the TITLE (so "quantum sensors for gravitational-wave
#                   detection" survives its "quantum ..." negative).
#
# To hunt a DIFFERENT field, replace these three lists and SEARCH_TERMS below.
# -----------------------------------------------------------------------------
CORE_ANCHORS: list[str] = [
    # -- discipline words ------------------------------------------------
    "astronomy", "astronomer", "astronomical", "astrophysic", "astrochemi",
    "astrobiolog", "astrometr", "astroparticle", "astrostatistic",
    "astro-informatic", "asteroseismolog", "helioseismolog",

    # -- physics ---------------------------------------------------------
    "physics", "physicist", "theoretical physics", "experimental physics",
    "condensed matter", "quantum mechanics", "solid state", "particle physics",
    "nuclear physics", "atomic physics", "plasma physics", "optics", "acoustics",
    "cryogenics", "biophysics", "geophysics", "medical physics",

    # -- chemistry ----------------------------------------------------------------------
    "chemistry", "chemist", "inorganic chemistry", "organic chemistry",
    "physical chemistry", "quantum chemistry", "theoretical chemistry",
    "analytical chemistry", "biochemistry", "chemical engineering",
    "materials chemistry", "nanotechnology", "radiochemistry",
    "photochemistry", "electrochemistry", "computational chemistry",

    # -- biology ----------------------------------------------------------------------
    "biology", "biologist", "molecular biology", "cell biology",
    "genetics", "biochemistry", "microbiology", "immunology",
    "neuroscience", "evolutionary biology", "developmental biology",
    "bioinformatics", "systems biology", "biophysics", "biotechnology",
    "ecology", "environmental biology", "genomics", "proteomics",
    "tissues", "tumor biology", "stem cell",

    # -- earth & space sciences ---------------------------------------------------------
    "geology", "geologist", "geophysics", "geodesy", "seismology",
    "volcanology", "hydrology", "oceanography", "meteorology",
    "climatology", "environmental science", "paleontology", "sedimentology",
    "soil science", "planetary science", "astrogeology",
    "mineralogy", "petrology", "structural geology",

    # -- engineering -------------------------------------------------------------------
    "computer science", "computer engineering", "software engineering",
    "electrical engineering", "electronic engineering", "mechanical engineering",
    "civil engineering", "chemical engineering", "aerospace engineering",
    "materials engineering", "biomedical engineering", "industrial engineering",
    "systems engineering", "data science", "artificial intelligence",
    "machine learning", "robotics", "automation", "network engineering",
    "signal processing", "control systems", "nuclear engineering",
    "materials science", "nanoengineering", "energy engineering",

    # -- economics -------------------------------------------------------------------
    "economics", "economist", "macroeconomics", "microeconomics",
    "international economics", "development economics", "game theory",
    "behavioral economics", "financial economics", "labor economics",
    "econometrics", "quantitative economics", "economic history",
    "public economics", "economic policy", "banks", "financial markets",

    # -- interdisciplinary sciences -----------------------------------------
    "data science", "statistical science", "quantitative analysis",
    "computational science", "informatics", "bioinformatics",
    "technological innovation", "innovation management",
    "cosmology", "cosmological", "cosmic microwave background", "CMB",
    "cosmic ray", "dark matter", "dark energy", "large-scale structure",
    "reionization", "reionisation", "early universe", "primordial",
    "gravitational wave", "gravitational lensing", "microlensing",
    "galaxy", "galaxies", "galactic", "extragalactic", "milky way",
    "interstellar", "ISM", "intergalactic", "circumgalactic",
    "molecular cloud", "nebula", "star formation", "starburst",
    "active galactic", "AGN", "quasar", "blazar", "supermassive",
    "stellar", "protostellar", "star cluster", "globular cluster",
    "binary star", "white dwarf", "neutron star", "black hole", "pulsar",
    "magnetar", "supernova", "kilonova", "gamma-ray burst", "GRB",
    "fast radio burst", "x-ray binar", "time-domain astronomy",
    "transient astronomy", "tidal disruption", "accretion dis",
    "compact object",
    "exoplanet", "extrasolar planet", "planet formation", "planetary science",
    "planetary system", "protoplanetary", "circumstellar",
    "planetary atmosphere", "asteroid", "comet", "kuiper belt", "meteorite",
    "planetesimal", "solar system", "planetolog", "cosmochemi",
    "habitability", "biosignature",
    "solar physics", "heliophysic", "heliosphere", "solar wind",
    "solar flare", "coronal", "sunspot", "space weather", "magnetosphere",
    "solar magnetic", "space plasma", "plasma astrophysic",
    "astrophysical plasma", "magnetohydrodynamic", "MHD",
    "cosmic magnetism", "interstellar magnetic",
    "observatory", "telescope", "observational astronomy", "radio astronomy",
    "radio interferomet", "submillimet", "x-ray astronomy",
    "gamma-ray astronomy", "infrared astronomy", "ultraviolet astronomy",
    "optical astronomy", "multi-messenger", "multimessenger",
    "neutrino astronomy", "spectrograph", "sky survey", "galaxy survey",
    "photometric survey", "astronomical instrument", "cherenkov", "euclid",
    "VLBI", "JWST", "HST", "LSST", "SDSS", "ALMA", "LOFAR", "LIGO", "SKA",
    "EHT", "VLT", "XMM", "SETI",
]

CONTEXT_TERMS: list[str] = [
    "observational", "theoretical", "numerical", "simulation",
    "computational", "instrumentation", "spectroscop", "polarimetr",
    "photometr", "interferometr", "plasma", "survey", "imaging",
    "data analysis", "machine learning", "deep learning", "magnetism",
    "magnetic field", "magnetized", "magnetised", "adaptive optics",
    "detector", "bayesian", "monte carlo", "n-body", "hydrodynamic",
    "radiative transfer", "turbulence", "dynamo", "time series", "pipeline",
    "image processing", "signal processing", "big data", "statistical",
    "cryogenic", "spectral", "high-performance computing", "GPU",
]

NEGATIVE_TERMS: list[str] = [
    "quantum optic", "quantum information", "quantum comput",
    "quantum technolog", "quantum material", "quantum dot", "quantum network",
    "qubit", "condensed matter", "solid state physics", "solid-state physics",
    "photonic", "semiconductor", "nanophotonic", "optoelectronic",
    "materials science", "material science", "nanomaterial", "nanostructure",
    "nanotechnolog", "2d material", "graphene", "polymer", "battery",
    "batteries", "photovoltaic", "solar cell", "fuel cell", "catalys",
    "electrochem", "biophysic", "medical physic", "radiotherapy",
    "medical imaging", "biomedical", "cancer", "clinical", "drug", "protein",
    "cell biology", "neuroscien", "genomic", "immunolog", "microbiolog",
    "accelerator physic", "particle accelerator", "accelerator engineering",
    "beam physics", "collider", "spintronic", "magnon", "ultracold",
    "cold atom", "atom trap", "ion trap", "optomechanic", "ultrafast",
    "laser physics", "fibre laser", "fiber laser", "tokamak",
    "fusion reactor", "inertial confinement", "plasma etching",
    "scanning tunneling", "scanning tunnelling", "electron microscop",
    "atomic force microscop", "metamaterial", "terahertz", "NMR", "MRI",
    "steelmaking", "corrosion", "welding", "manufacturing", "supply chain",
    "geotechnical",
]

# Scoring weights (title evidence counts far more than description evidence)
# and the acceptance rule:  keep iff  (>=1 core anchor)  AND  (score >= threshold).
# With the defaults: one core anchor in the TITLE scores 5.0 (pass), one core
# anchor in the DESCRIPTION alone scores 2.5 (pass), context-only posts have no
# anchor (fail), and a description-only anchor plus a negative term scores
# 2.5 - 2.0 = 0.5 (fail) — but negatives are ignored when the TITLE carries an
# anchor, so genuine crossovers survive.
RELEVANCE_WEIGHTS = {
    "core_title": 5.0,       # per distinct core anchor found in the title
    "core_desc": 2.5,        # per distinct core anchor found only in the desc
    "context_title": 1.0,    # per distinct context term in the title
    "context_desc": 0.5,     # per distinct context term only in the desc
    "negative": -2.0,        # per distinct negative term (skipped if a core
                             # anchor appears in the title)
}
RELEVANCE_THRESHOLD = 2.0    # minimum score to keep (see rule above)

# Terms typed into each site's own search box (coverage, not filtering — the
# relevance engine above decides what is kept). Order matters: sources that
# only take a few queries use the first entries.
SEARCH_TERMS = [
    "astronomy", "astrophysics", "cosmology", "exoplanet",
    "gravitational wave", "interstellar medium",
]

# Region filter. ["*"] (or []) = worldwide / no geo filter.
# Otherwise list country names, e.g. ["Germany", "Netherlands", "Japan"].
COUNTRIES = ["*"]

# Which career levels to keep. To hunt postdocs instead, set ["postdoc"];
# for both, ["phd", "postdoc"]. Recognised: phd, postdoc, faculty, staff.
# With the default ["phd"], postdoc/faculty/staff posts are STRICTLY excluded.
WANTED_POSITION_TYPES = ["phd"]
# Keep entries whose level can't be determined and flag them (position_type="unknown").
KEEP_AMBIGUOUS = True

# Drop positions whose deadline is strictly before today.
# Positions with NO (or unparseable) deadline are KEPT.
EXCLUDE_EXPIRED = True

# Enable/disable sources independently.
SOURCES_ENABLED: dict[str, bool] = {
    "euraxess":         True,   # [HTML] EURAXESS faceted search (Europe)
    "nature_careers":   True,   # [FEED/HTML] Nature Careers
    "jobs_ac_uk":       True,   # [HTML] jobs.ac.uk (UK, PhD facet)
    "findaphd":         True,   # [JS]  FindAPhD (Cloudflare — see docstring)
    "academictransfer": True,   # [JS]  AcademicTransfer (NL) API interception
    "academicjobsonline": True, # [HTML] AcademicJobsOnline astro categories
    "aas":              True,   # [FEED/JS] AAS Job Register (Cloudflare)
    "jrecin":           True,   # [HTML] JREC-IN Portal (Japan)
    "eso":              True,   # [FEED] ESO recruitment RSS
    "esa":              True,   # [HTML] ESA careers search
    "iau":              False,  # [STUB] job board removed from iau.org
    "astrobetter":      False,  # [STUB] rumor mill = postdoc/faculty, not PhD
    "linkedin":         True,   # [HTML] LinkedIn guest job search (see docstring
                                #        re ToS/robots — personal use only)
    "uni_departments":  True,   # [HTML] physics/astronomy dept pages of top
                                #        universities (Europe/Japan/China sweep)
    "seed_urls":        True,   # [HTML] hand-picked URLs from SEED_FILE
                                #        (+ sibling postings on the same boards)
    "china":            False,  # [STUB] CAS institutes now covered by
                                #        uni_departments; boards stay stubbed
    "korea":            False,  # [STUB]
    "new_zealand":      False,  # [STUB]
}

# Output base path. ".csv", ".json" and ".html" are appended (any extension
# you give is stripped). A previous JSON at this path drives NEW detection.
OUTPUT_PATH = "astra_positions"
WRITE_HTML = True             # also write the results.html dashboard

# Proxy applied to ALL traffic (requests, curl_cffi, headless browser).
# V2RayN default SOCKS inbound; HTTP inbound variant: "http://127.0.0.1:10809".
# Set to None (or pass --proxy "") to disable.
PROXY: Optional[str] = "socks5h://127.0.0.1:10808"
# If the proxy port is closed (e.g. V2Ray in system-wide TUN mode), continue
# without it instead of failing every request.
PROXY_FALLBACK_DIRECT = True
# Auto-detect a working local proxy: if the configured one is dead (or unset),
# sweep the well-known local ports below and use the first one that REALLY
# routes traffic. Lets the tool keep working whichever VPN app you run
# (V2RayN, Clash, sing-box, ...) and on whatever port. Set False to keep the
# old behavior (configured proxy or direct).
AUTO_DETECT_PROXY = True
# Candidate local proxies, (url, label), checked in order until one works.
# The configured PROXY (if any) is always tried FIRST; only then this sweep.
PROXY_CANDIDATES: list[tuple[str, str]] = [
    ("socks5h://127.0.0.1:10808", "V2RayN SOCKS"),
    ("http://127.0.0.1:10809",     "V2RayN HTTP"),
    ("http://127.0.0.1:7890",      "Clash HTTP"),
    ("socks5h://127.0.0.1:7891",   "Clash SOCKS"),
    ("socks5h://127.0.0.1:1080",   "generic SOCKS"),
    ("http://127.0.0.1:1080",      "generic HTTP"),
    ("http://127.0.0.1:2080",      "V2rayNG HTTP"),
    ("socks5h://127.0.0.1:2080",   "V2rayNG SOCKS"),
    ("http://127.0.0.1:8888",      "common HTTP proxy"),
    ("socks5h://127.0.0.1:20171",  "v2rayN other SOCKS"),
    ("http://127.0.0.1:20171",     "v2rayN other HTTP"),
]
# Tiny, stable endpoint used to verify a proxy actually routes traffic (a
# listening port is not a working proxy) and to probe direct connectivity.
PROBE_URL = "https://api.ipify.org"
PROBE_TIMEOUT = 5.0            # seconds for each proxy/direct probe

# When a Cloudflare challenge defeats the headless browser AND a desktop
# display is available, retry once with a visible Chrome window (a real
# browser pass — not evasion). Set False to never open a window.
HEADED_FALLBACK = True

CONNECT_TIMEOUT = 8           # seconds to establish a connection (fast fail)
REQUEST_TIMEOUT = 20          # seconds per request (read)
MAX_RETRIES = 3               # retries on connect/read/5xx/429
BACKOFF_FACTOR = 0.8          # exponential backoff base
REQUEST_DELAY = 2.0           # polite min seconds between requests (per process)
ROBOTS_OBEY = True            # honor robots.txt (override with --no-robots)
USER_AGENT = ("phd-position-aggregator/2.0 "
              "(+research use; contact: your-email@example.com)")

MAX_DESC_CHARS = 400          # truncate short_description to this many chars

# -----------------------------------------------------------------------------
# FIELD PROFILES (external YAML — lets non-coders retarget the whole tool)
#
# The taxonomy above is the built-in ASTRONOMY default. If PyYAML is installed
# and fields/<FIELD_PROFILE>.yaml exists, it REPLACES the taxonomy, search
# terms and subfields; config.yaml (same directory as this script, or the
# working directory) can override the runtime settings in this block. Select a
# profile at runtime with --field <name>. See fields/template.yaml to write
# your own.
# -----------------------------------------------------------------------------
FIELD_PROFILE = "astronomy"   # default profile name (fields/astronomy.yaml)
CONFIG_FILE = "config.yaml"   # optional runtime-settings override file
FIELDS_DIR = "fields"         # directory holding <profile>.yaml files

# Subfields of the active profile — used by --find-supervisors (and available
# as extra search focus). Overridden by the profile YAML's `subfields:` block.
SUBFIELDS: dict[str, dict] = {
    "ism": {
        "label": "Interstellar medium & star formation",
        "keywords": ["interstellar medium", "molecular cloud", "star formation",
                     "dust", "HII region", "photodissociation region"],
    },
    "magnetism": {
        "label": "Cosmic magnetism & Faraday methods",
        "keywords": ["magnetic field", "Faraday rotation", "polarization",
                     "synchrotron", "dynamo", "rotation measure"],
    },
    "cosmology": {
        "label": "Cosmology & large-scale structure",
        "keywords": ["cosmology", "dark matter", "dark energy",
                     "large-scale structure", "cosmic microwave background"],
    },
    "galaxies": {
        "label": "Galaxy formation & evolution",
        "keywords": ["galaxy evolution", "galaxy formation", "AGN",
                     "star formation history", "galactic dynamics"],
    },
    "exoplanets": {
        "label": "Exoplanets & planet formation",
        "keywords": ["exoplanet", "planet formation", "protoplanetary disk",
                     "planetary atmosphere", "transit photometry"],
    },
    "stellar": {
        "label": "Stars & compact objects",
        "keywords": ["stellar evolution", "supernova", "neutron star",
                     "white dwarf", "black hole", "pulsar"],
    },
    "radio": {
        "label": "Radio astronomy & surveys",
        "keywords": ["radio continuum", "radio survey", "interferometry",
                     "LOFAR", "SKA", "21 cm"],
    },
}

# -----------------------------------------------------------------------------
# SEED URLS (hand-picked position links the crawlers miss)
# -----------------------------------------------------------------------------
SEED_FILE = "seeds.txt"       # one URL per line, '#' comments allowed
SEED_BYPASS_GATE = True       # hand-picked seeds skip the relevance/type gates
                              # (still scored, classified and deadline-checked);
                              # False = seeds go through ALL normal filters
SEED_DISCOVER_SIBLINGS = True # also look for sibling postings on the same board
SEED_MAX_SIBLINGS = 8         # max sibling pages fetched per seed domain

# -----------------------------------------------------------------------------
# FRESHNESS (undated posts must not live forever)
#
# Effective-date priority per record: future deadline > posted_date >
# first-seen timestamp from STATE_FILE > a date read off the page itself.
# A post with NO future deadline whose effective date is older than
# MAX_AGE_DAYS is dropped as stale. A truly dateless post is kept on FIRST
# discovery (its first-seen date then ages it naturally on later runs).
# -----------------------------------------------------------------------------
MAX_AGE_DAYS = 365
KEEP_UNDATED_WITHIN_WINDOW = True
STATE_FILE = ".seen_positions.json"   # per-URL first/last-seen (gitignored)
MAX_PAGE_DATE_PROBES = 10     # cap on "read a date off the page" fetches / run

# -----------------------------------------------------------------------------
# SUPERVISOR FINDER (--find-supervisors --field <subfield> --country <name>)
#
# PRIMARY: NASA ADS API. Get a free personal token at
# https://ui.adsabs.harvard.edu/user/settings/token and export it as
# ADS_API_TOKEN (or put it in a gitignored .env file). NEVER commit it.
# FALLBACK: arXiv API (no token; affiliations are best-effort).
# -----------------------------------------------------------------------------
ADS_API_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_TOKEN_ENV = "ADS_API_TOKEN"
SUPERVISOR_YEARS_BACK = 5     # publication window for "recent" papers
SUPERVISOR_MAX_PAPERS = 300   # papers pulled per query (ADS caps rows at 2000)
SUPERVISOR_MIN_PAPERS = 2     # authors on fewer matched papers are dropped
SUPERVISOR_MAX_AUTHORS = 40   # skip mega-collaboration papers (author count)
SUPERVISOR_SENIOR_WEIGHT = 2.0  # extra score per LAST-author (PI) appearance
SUPERVISOR_ORCID_EMAILS = True  # look up PUBLIC emails on ORCID for top hits
SUPERVISOR_ADS_DB = "astronomy"   # ADS database facet to search: astronomy |
                                  # physics | general (= arXiv) | all (no filter)
SUPERVISOR_ARXIV_CAT = "astro-ph*"  # arXiv category filter for the tokenless
                                # fallback; "all" searches every category, and
                                # commas OR several ("econ.*,q-fin.*")
                                # (only self-published contacts; never guessed)
# Which literature feeds --find-supervisors. ADS only indexes astronomy +
# physics, so other majors (CS, economics, biology, chemistry, engineering...)
# are served by OpenAlex, which covers EVERY discipline with no API token:
#   auto     = ADS for astronomy/physics (best index there), OpenAlex otherwise
#   openalex = OpenAlex only (works for ANY major, no token needed)
#   ads      = NASA ADS only (needs ADS_API_TOKEN)
#   arxiv    = arXiv only
SUPERVISOR_SOURCE = "auto"
# Author-direct supervisor search (non-astro majors): instead of aggregating
# keyword-matched PAPERS (which rewards prolific juniors and leaks neighbouring
# fields), query the OpenAlex AUTHOR index via the profile's curated TOPICS +
# a country filter, sort by citations, then enrich the top candidates with
# their RECENT works (titles/DOIs + activity check).
SUPERVISOR_AUTHOR_PER_PAGE = 50   # author records fetched per topics batch
SUPERVISOR_AUTHOR_ENRICH = 80     # pool candidates enriched with recent works +
                                  # scored — the top-N by h-index / recency
SUPERVISOR_POOL_PAGES = 3         # max works pages (100 works each) fetched per
                                  # topics batch to seed the candidate pool
SUPERVISOR_RECENT_WORKS = 25      # recent works pulled per candidate to verify
                                  # country + field + activity (was 3)
SUPERVISOR_RECENCY_WEIGHT = 1.0   # score per recent paper in the window
SUPERVISOR_COUNTRY_BOOST = 2.0    # extra score when recent works confirm the
                                  # author is actually IN the target country
# --- balanced candidate verification (openalex_supervisor_authors) ----------
# An author must, among their OWN recent works that carry country data, have at
# least this SHARE (default majority) from the target country — so a lone
# CEPR/NBER/Ifo-style research-network paper can no longer misplace a foreign
# professor, while genuine in-country researchers still pass.
SUPERVISOR_MIN_IN_COUNTRY_SHARE = 0.5
# Of the candidate's recent works, at least this SHARE must belong to the
# profile's OpenAlex field (supervisor_field). This drops namesake doctors /
# biotech / unrelated researchers whose author "topics" are broad.
SUPERVISOR_MIN_FIELD_SHARE = 0.4
# Per-profile seniority signal: which authorship position marks the PI.
#   last_author     astronomy/physics style — last author is the supervisor
#   corresponding   biology/chemistry style — corresponding author is the PI
#   none            alphabetical order (economics/finance) — no position bonus
SUPERVISOR_SENIOR_SIGNAL = "last_author"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_AUTHORS_API = "https://api.openalex.org/authors"
# OpenAlex asks a real e-mail (polite pool, ~10 req/s). Override via the
# OPENALEX_MAILTO environment variable; never a requirement, only a courtesy.
OPENALEX_MAILTO = "phd-aggregator@localhost"

# --- anti-bot / browser persistence (Task: beat Cloudflare politely) ----------
BROWSER_PROFILE_DIR = ".pw_profile"   # persistent Chromium user-data dir (gitignored):
                                      # cookies/localStorage survive BETWEEN runs, so a
                                      # site that trusted us yesterday still trusts us today
CHALLENGE_WAIT_MS = 8000              # ms we give a Cloudflare interstitial to auto-clear
# curl_cffi TLS-impersonation targets, newest first; we rotate through these
# on consecutive blocked requests (and skip any the installed curl_cffi lacks)
CURL_IMPERSONATION = ["chrome136", "chrome131", "chrome124",
                      "chrome120", "chrome110", "chrome"]
CURL_IMPERSONATION_FALLBACK = "chrome"

# =============================================================================
# end CONFIG
# =============================================================================


# -----------------------------------------------------------------------------
# Config object (lets the CLI override the constants above without editing them)
# -----------------------------------------------------------------------------
@dataclass
class Config:
    core_anchors: list[str]
    context_terms: list[str]
    negative_terms: list[str]
    weights: dict[str, float]
    threshold: float
    search_terms: list[str]
    countries: list[str]
    wanted_types: list[str]
    keep_ambiguous: bool
    sources_enabled: dict[str, bool]
    output_path: str
    write_html: bool
    proxy: Optional[str]
    proxy_fallback_direct: bool
    headed_fallback: bool
    timeout: int
    max_retries: int
    backoff: float
    delay: float
    robots_obey: bool
    user_agent: str
    max_desc: int
    exclude_expired: bool = True
    strict_phd_only: bool = False
    # Require a core anchor in the TITLE for the relevance gate (description
    # matches then only boost the score, never qualify alone). Per-profile:
    #   require_title_anchor: true
    # Keeps e.g. a computer_science search from surfacing ML-heavy posts from
    # other fields (astrophysics, ...) whose descriptions mention CS methods.
    require_title_anchor: bool = False
    # --- network / proxy auto-detection ---
    auto_detect_proxy: bool = AUTO_DETECT_PROXY
    connect_timeout: int = CONNECT_TIMEOUT
    # Honour a server's Retry-After on 429? True for crawling (polite, and a
    # crawl has all night). False for anything a person is waiting on: the
    # sleep happens inside urllib3, out of reach of the read timeout AND of
    # every cancel check, so a throttled API can freeze an interactive search
    # for minutes with a dead Stop button. Retries still happen either way —
    # only the wait between them changes, to bounded exponential backoff.
    respect_retry_after: bool = True
    # --- anti-bot / browser (Task: persistent profile + stealth) ---
    browser_profile_dir: str = BROWSER_PROFILE_DIR
    browser_headless: Optional[bool] = None    # None = default headless
    challenge_wait_ms: int = CHALLENGE_WAIT_MS
    debug: bool = False
    # --- field profile (Task: adaptability) ---
    field_profile: str = FIELD_PROFILE
    subfield: Optional[str] = None          # e.g. "ism" for --find-supervisors
    subfields: dict = field(default_factory=lambda: dict(SUBFIELDS))
    # Subfield ids the user picked for THIS run (multi-select). Boosts position
    # scoring; filters supervisor topics. See apply_subfield_focus().
    selected_subfields: list = field(default_factory=list)
    # per-profile university department registry for source_uni_departments
    # (list of {country, institution, url, field_specific}); empty + explicit
    # = disable the source, absent = fall back to the built-in astronomy
    # UNIVERSITY_DEPARTMENTS registry
    departments: list = field(default_factory=list)
    departments_explicit: bool = False
    # Boards this field claims for itself, from the profile's `sources:` block.
    # These are ADDED to the general multi-discipline boards and to any source
    # that names the field in its own @register_source(fields=...) declaration.
    # See sources.base.resolve_sources_for_field.
    profile_sources: list = field(default_factory=list)
    # Opt-in for measurably-slow sources (the university department sweep).
    # OFF by default so a normal search is never held up for minutes.
    include_slow_sources: bool = False
    # Per-source knobs from the profile's `source_options:` block, e.g. which
    # EURAXESS research-field facets or AcademicJobsOnline categories THIS
    # discipline should query. Read via Config.source_option().
    source_options: dict = field(default_factory=dict)
    # --- seed URLs ---
    seed_file: str = SEED_FILE
    seed_bypass_gate: bool = SEED_BYPASS_GATE
    seed_discover_siblings: bool = SEED_DISCOVER_SIBLINGS
    seed_max_siblings: int = SEED_MAX_SIBLINGS
    # --- freshness ---
    max_age_days: int = MAX_AGE_DAYS
    keep_undated_within_window: bool = KEEP_UNDATED_WITHIN_WINDOW
    state_path: str = STATE_FILE
    max_page_date_probes: int = MAX_PAGE_DATE_PROBES
    # --- HTTP cache (M2: incremental conditional-GET crawl) ---
    http_cache: bool = True          # persistent ETag/Last-Modified revalidation
    force_refresh: bool = False      # --force-refresh: bypass the cache this run
    # --- supervisor finder ---
    supervisor_years_back: int = SUPERVISOR_YEARS_BACK
    supervisor_min_papers: int = SUPERVISOR_MIN_PAPERS
    supervisor_ads_db: str = SUPERVISOR_ADS_DB
    # True when the field profile named an ADS collection itself, rather than
    # inheriting the astronomy default. supervisors.chain uses this to avoid
    # routing a NEW field's supervisor search to an astronomy database.
    supervisor_ads_db_explicit: bool = False
    supervisor_arxiv_cat: str = SUPERVISOR_ARXIV_CAT
    supervisor_source: str = SUPERVISOR_SOURCE   # auto | openalex | ads | arxiv
    # Author-direct (OpenAlex) tuning, per-major:
    supervisor_field: Optional[str] = None       # OpenAlex field id, e.g. "20"
    supervisor_topics: list[str] = field(default_factory=list)  # curated topics
    supervisor_senior_signal: str = SUPERVISOR_SENIOR_SIGNAL
    #                   none | last_author | corresponding
    supervisor_author_per_page: int = SUPERVISOR_AUTHOR_PER_PAGE
    supervisor_author_enrich: int = SUPERVISOR_AUTHOR_ENRICH
    supervisor_pool_pages: int = SUPERVISOR_POOL_PAGES
    supervisor_recent_works: int = SUPERVISOR_RECENT_WORKS
    supervisor_min_in_country_share: float = SUPERVISOR_MIN_IN_COUNTRY_SHARE
    supervisor_min_field_share: float = SUPERVISOR_MIN_FIELD_SHARE
    # compiled taxonomy: lists of (term, regex); built by compile_taxonomy()
    _core_rx: list = field(default_factory=list, repr=False)
    _context_rx: list = field(default_factory=list, repr=False)
    _negative_rx: list = field(default_factory=list, repr=False)

    @property
    def stem(self) -> str:
        base, _ext = os.path.splitext(self.output_path)
        return base or self.output_path

    @property
    def csv_path(self) -> str:
        return self.stem + ".csv"

    @property
    def json_path(self) -> str:
        return self.stem + ".json"

    @property
    def html_path(self) -> str:
        return self.stem + ".html"

    @property
    def geo_filter_active(self) -> bool:
        return bool(self.countries) and "*" not in self.countries

    def source_option(self, source: str, key: str, default=None):
        """One knob from the active profile's ``source_options:`` block.

        ``source_options: {euraxess: {research_fields: [47]}}`` is read as
        ``cfg.source_option("euraxess", "research_fields")``. Returns
        ``default`` when the profile says nothing, so every source keeps a
        working built-in fallback and a thin profile is never a crash.
        """
        opts = self.source_options.get(source)
        if not isinstance(opts, dict):
            return default
        value = opts.get(key, default)
        return default if value is None else value


# -----------------------------------------------------------------------------
# External configuration: config.yaml (runtime settings) + fields/*.yaml
# (field profiles). Everything is OPTIONAL — with no YAML files (or no PyYAML)
# the built-in astronomy defaults above are used unchanged.
# -----------------------------------------------------------------------------
def _script_dir() -> str:
    try:
        # This module lives in <aggregator>/core/, so the aggregator dir is the
        # PARENT of this file — config.yaml / fields/*.yaml / .env sit next to
        # astra.py, not inside core/.
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        return os.getcwd()


def _find_config_path(name: str) -> Optional[str]:
    """Look for a config file in the working directory, then next to the
    script, then (for a frozen/packaged binary) next to the executable — so the
    tool finds config.yaml whether run in-place, installed, or bundled as the
    desktop sidecar (whose CWD is the app-data dir)."""
    bases = [os.getcwd(), _script_dir()]
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(os.path.abspath(sys.executable)))
    for base in bases:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return None


def _load_yaml_file(path: str) -> Optional[dict]:
    if not _HAVE_YAML:
        log.warning("PyYAML not installed — ignoring %s (pip install pyyaml "
                    "to use external config files)", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data is None:
            return {}
        if not isinstance(data, dict):
            log.warning("%s: top level must be a mapping — ignored", path)
            return None
        return data
    except Exception as exc:
        log.warning("could not parse %s: %s — using built-in defaults", path, exc)
        return None


def load_field_profile(name: str) -> Optional[dict]:
    """Load fields/<name>.yaml (searched in CWD and next to the script)."""
    for base in (os.getcwd(), _script_dir()):
        p = os.path.join(base, FIELDS_DIR, f"{name}.yaml")
        if os.path.isfile(p):
            data = _load_yaml_file(p)
            if data is not None:
                data["_path"] = p
            return data
    return None


def list_field_profiles() -> list[str]:
    names: set[str] = set()
    for base in (os.getcwd(), _script_dir()):
        d = os.path.join(base, FIELDS_DIR)
        if os.path.isdir(d):
            names.update(f[:-5] for f in os.listdir(d)
                         if f.endswith(".yaml") and not f.startswith("_"))
    return sorted(n for n in names if n != "template")


# Below this length a term is not safe as a SQL LIKE '%term%' fragment: it
# matches INSIDE unrelated words. The single worst case was "R" (a
# statistics/data-science context term), whose '%r%' matched essentially every
# supervisor row and turned the field filter into a no-op.
_MIN_FILTER_KEYWORD = 3


def field_profile_keywords(name: str) -> list[str]:
    """QUALIFYING terms for a field profile name — used as a FILTER.

    Expands a ``fields/<name>.yaml`` profile into a lowercased, deduplicated
    list taken from ``core_anchors`` and the ``keywords`` of every subfield.
    Returns ``[]`` when the profile is missing or carries no terms — callers
    should treat an empty list as "no results", NOT as "match everything".

    ``context_terms`` are DELIBERATELY EXCLUDED, and that is the whole point of
    this function. The field schema defines them as boost-only: "context terms
    BOOST a matching post's score but can NEVER qualify a post on their own".
    Every caller here uses the result to decide what a field *includes*, which
    is precisely the qualifying decision context terms must not make. Including
    them meant a supervisor search for statistics filtered on "machine
    learning", "simulation", "benchmark", "collaboration", "prior" and "R" —
    so the query became `topics LIKE '%r%' OR ...` and returned supervisors
    from every discipline. That is the "results are not filtered" bug.

    Terms shorter than three characters are dropped for the same reason: this
    list is matched as a substring, with no word boundaries available in SQL
    LIKE, so a short term matches inside longer unrelated words.

    SHORT ALL-CAPS ACRONYMS ARE DROPPED TOO, and not because they are bad
    terms — because this function destroys the very rule that makes them safe.
    The field schema matches an ALL-CAPS term of <= 6 characters as a
    case-SENSITIVE WHOLE WORD, exactly so that "AGN" cannot fire inside
    "magnetic". Lowercasing one into a substring pattern throws that away:
    '%tem%' matches "system", '%sem%' matches "assembly", '%ert%' matches
    "expert", '%ism%' matches "mechanism". Their full-phrase neighbours in the
    same profile still match ("brain-computer interface" for a profile whose
    acronym is EEG), so the recall cost is small and the precision cost of
    keeping them is not.
    """
    profile = load_field_profile(name)
    if not profile:
        return []
    keywords: list[str] = []
    if isinstance(profile.get("core_anchors"), list):
        keywords.extend(str(k) for k in profile["core_anchors"]
                        if isinstance(k, str))
    subfields = profile.get("subfields")
    if isinstance(subfields, dict):
        for sub in subfields.values():
            if isinstance(sub, dict) and isinstance(sub.get("keywords"), list):
                keywords.extend(str(k) for k in sub["keywords"] if isinstance(k, str))

    def _safe(term: str) -> bool:
        t = term.strip()
        if len(t) < _MIN_FILTER_KEYWORD:
            return False
        # The schema's own acronym rule: ALL-CAPS, <= 6 chars, no lowercase.
        if len(t) <= 6 and t.isupper() and any(c.isalpha() for c in t):
            return False
        return True

    return list(dict.fromkeys(k.lower() for k in keywords if _safe(k)))


def _oa_field_id(value: object) -> Optional[str]:
    """'https://openalex.org/fields/20' | 'fields/20' | '20' -> '20'.

    A dict (e.g. an OpenAlex `primary_topic.field` node) is read via its "id"
    key first, so callers can hand over raw API nodes without unwrapping."""
    if isinstance(value, dict):
        value = value.get("id")
    m = re.search(r"(?:fields/)?(\d+)\s*$", str(value or "").strip())
    return m.group(1) if m else None


def apply_field_profile(cfg: Config, profile: dict) -> None:
    """Overlay a parsed fields/*.yaml profile onto the config. Only the keys
    present in the YAML are replaced; everything else keeps its default."""
    str_lists = {"core_anchors": "core_anchors", "context_terms": "context_terms",
                 "negative_terms": "negative_terms", "search_terms": "search_terms"}
    for yaml_key, attr in str_lists.items():
        val = profile.get(yaml_key)
        if isinstance(val, list) and all(isinstance(x, str) for x in val):
            setattr(cfg, attr, list(val))
        elif val is not None:
            log.warning("field profile: %r must be a list of strings — ignored",
                        yaml_key)
    if isinstance(profile.get("weights"), dict):
        cfg.weights = {**cfg.weights,
                       **{k: float(v) for k, v in profile["weights"].items()
                          if k in cfg.weights}}
    if profile.get("threshold") is not None:
        try:
            cfg.threshold = float(profile["threshold"])
        except (TypeError, ValueError):
            log.warning("field profile: bad threshold %r — ignored",
                        profile["threshold"])
    if isinstance(profile.get("require_title_anchor"), bool):
        cfg.require_title_anchor = profile["require_title_anchor"]
        log.info("field profile: require_title_anchor=%s",
                 cfg.require_title_anchor)
    for yaml_key, attr in (("supervisor_ads_db", "supervisor_ads_db"),
                           ("supervisor_arxiv_cat", "supervisor_arxiv_cat"),
                           ("supervisor_source", "supervisor_source")):
        if isinstance(profile.get(yaml_key), str):
            setattr(cfg, attr, profile[yaml_key])
            if yaml_key == "supervisor_ads_db":
                cfg.supervisor_ads_db_explicit = True
            log.info("field profile: %s=%r", yaml_key, profile[yaml_key])
    # --- author-direct supervisor finder (OpenAlex topics), per major ---------
    fid = _oa_field_id(profile.get("supervisor_field"))
    if fid is not None:
        cfg.supervisor_field = fid
        log.info("field profile: supervisor_field=%s (OpenAlex)", fid)
    topics = profile.get("supervisor_topics")
    if isinstance(topics, list) and topics:
        cfg.supervisor_topics = [str(t).strip() for t in topics if str(t).strip()]
        log.info("field profile: %d supervisor_topics loaded",
                 len(cfg.supervisor_topics))
    if isinstance(profile.get("supervisor_senior_signal"), str):
        signal = profile["supervisor_senior_signal"].strip().lower()
        if signal in ("none", "last_author", "corresponding"):
            cfg.supervisor_senior_signal = signal
            log.info("field profile: supervisor_senior_signal=%s", signal)
        else:
            log.warning("field profile: bad supervisor_senior_signal %r — "
                        "expected none|last_author|corresponding", signal)
    # --- author-direct supervisor finder tuning knobs (per-major overrides) ---
    int_knobs = {"supervisor_author_per_page": "supervisor_author_per_page",
                 "supervisor_author_enrich": "supervisor_author_enrich",
                 "supervisor_pool_pages": "supervisor_pool_pages",
                 "supervisor_recent_works": "supervisor_recent_works"}
    for yaml_key, attr in int_knobs.items():
        val = profile.get(yaml_key)
        if isinstance(val, int) and val > 0:
            setattr(cfg, attr, val)
        elif val is not None:
            log.warning("field profile: %r must be a positive int — ignored",
                        yaml_key)
    float_knobs = {"supervisor_min_in_country_share":
                       "supervisor_min_in_country_share",
                   "supervisor_min_field_share": "supervisor_min_field_share"}
    for yaml_key, attr in float_knobs.items():
        val = profile.get(yaml_key)
        if isinstance(val, (int, float)) and 0.0 < float(val) <= 1.0:
            setattr(cfg, attr, float(val))
        elif val is not None:
            log.warning("field profile: %r must be a number in (0,1] — ignored",
                        yaml_key)
    if isinstance(profile.get("subfields"), dict):
        cfg.subfields = {
            str(k): v for k, v in profile["subfields"].items()
            if isinstance(v, dict) and isinstance(v.get("keywords"), list)
        }
    # Optional per-field department registry for source_uni_departments:
    #   departments:
    #     - country: Germany
    #       institution: Max Planck Institute for Radio Astronomy
    #       url: https://www.mpifr-bonn.mpg.de/joboffers
    #       field_specific: true        # "this dept is YOUR field" (default false)
    if isinstance(profile.get("departments"), list):
        cleaned: list[dict] = []
        for d in profile["departments"]:
            if not isinstance(d, dict):
                continue
            url = d.get("url")
            if not url or not isinstance(url, str):
                log.warning("field profile: departments entry missing a URL — "
                            "skipped (%r)", d)
                continue
            cleaned.append({
                "country": str(d.get("country") or "Unknown"),
                "institution": str(d.get("institution") or url),
                "url": url.strip(),
                "field_specific": bool(d.get("field_specific")),
            })
        cfg.departments = cleaned
        cfg.departments_explicit = True
    # Optional per-field board list — the job boards, societies and databases
    # that actually serve THIS discipline:
    #   sources:
    #     - acs_careers
    #     - rsc_jobs
    # Names must match a @register_source name (`--list-sources`). This is how
    # a new field claims a specialist board without touching any Python; the
    # general multi-discipline boards are always added on top.
    if isinstance(profile.get("sources"), list):
        cfg.profile_sources = [str(s).strip() for s in profile["sources"]
                               if str(s).strip()]
        log.info("field profile: %d dedicated source(s) declared",
                 len(cfg.profile_sources))
    elif profile.get("sources") is not None:
        log.warning("field profile: `sources` must be a list of source names "
                    "— ignored")
    # Optional per-source knobs, e.g. which EURAXESS research-field facets or
    # AcademicJobsOnline categories THIS discipline should ask for:
    #   source_options:
    #     euraxess: {research_fields: [47]}     # 47 = Chemistry
    #     academicjobsonline: {categories: [chemistry]}
    if isinstance(profile.get("source_options"), dict):
        cfg.source_options = {
            str(name): dict(opts)
            for name, opts in profile["source_options"].items()
            if isinstance(opts, dict)
        }
        log.info("field profile: source_options for %s",
                 ", ".join(sorted(cfg.source_options)) or "(none)")
    elif profile.get("source_options") is not None:
        log.warning("field profile: `source_options` must be a mapping of "
                    "source name -> options — ignored")
        log.info("field profile: %d departments loaded for uni_departments",
                 len(cleaned))


def apply_config_yaml(cfg: Config, data: dict) -> None:
    """Overlay config.yaml runtime settings (proxy, sources, filters, seeds,
    freshness ...). Unknown keys are reported, not fatal."""
    known_scalars = {
        "proxy": ("proxy", lambda v: (str(v) or None) if v else None),
        "proxy_fallback_direct": ("proxy_fallback_direct", bool),
        "headed_fallback": ("headed_fallback", bool),
        "output_path": ("output_path", str),
        "write_html": ("write_html", bool),
        "request_timeout": ("timeout", int),
        "max_retries": ("max_retries", int),
        "backoff_factor": ("backoff", float),
        "request_delay": ("delay", float),
        "robots_obey": ("robots_obey", bool),
        "user_agent": ("user_agent", str),
        "max_desc_chars": ("max_desc", int),
        "exclude_expired": ("exclude_expired", bool),
        "strict_phd_only": ("strict_phd_only", bool),
        "browser_profile_dir": ("browser_profile_dir", str),
        "browser_headless": ("browser_headless", bool),
        "challenge_wait_ms": ("challenge_wait_ms", int),
        "auto_detect_proxy": ("auto_detect_proxy", bool),
        "connect_timeout": ("connect_timeout", int),
        "keep_ambiguous": ("keep_ambiguous", bool),
        "threshold": ("threshold", float),
        "field_profile": ("field_profile", str),
        "seed_file": ("seed_file", str),
        "seed_bypass_gate": ("seed_bypass_gate", bool),
        "seed_discover_siblings": ("seed_discover_siblings", bool),
        "seed_max_siblings": ("seed_max_siblings", int),
        "max_age_days": ("max_age_days", int),
        "keep_undated_within_window": ("keep_undated_within_window", bool),
        "state_file": ("state_path", str),
        "max_page_date_probes": ("max_page_date_probes", int),
        "supervisor_years_back": ("supervisor_years_back", int),
        "supervisor_min_papers": ("supervisor_min_papers", int),
        "supervisor_source": ("supervisor_source", str),
        "supervisor_field": ("supervisor_field", str),
        "supervisor_senior_signal": ("supervisor_senior_signal", str),
        "supervisor_author_per_page": ("supervisor_author_per_page", int),
        "supervisor_author_enrich": ("supervisor_author_enrich", int),
        "supervisor_pool_pages": ("supervisor_pool_pages", int),
        "supervisor_recent_works": ("supervisor_recent_works", int),
        "supervisor_min_in_country_share": ("supervisor_min_in_country_share", float),
        "supervisor_min_field_share": ("supervisor_min_field_share", float),
    }
    for key, val in data.items():
        if key in ("countries", "wanted_position_types", "sources_enabled",
                   "country_aliases", "supervisor_topics"):
            continue  # handled below
        if key in known_scalars:
            attr, cast = known_scalars[key]
            try:
                setattr(cfg, attr, cast(val))
            except (TypeError, ValueError):
                log.warning("config.yaml: bad value for %r: %r — ignored", key, val)
        else:
            log.warning("config.yaml: unknown key %r — ignored", key)
    if isinstance(data.get("countries"), list):
        cfg.countries = [str(c) for c in data["countries"]]
    if isinstance(data.get("wanted_position_types"), list):
        cfg.wanted_types = [str(t).lower() for t in data["wanted_position_types"]]
    if isinstance(data.get("sources_enabled"), dict):
        for name, on in data["sources_enabled"].items():
            cfg.sources_enabled[str(name)] = bool(on)
    if isinstance(data.get("supervisor_topics"), list):
        cfg.supervisor_topics = [str(t).strip() for t in data["supervisor_topics"]
                                 if str(t).strip()]
    if isinstance(data.get("supervisor_senior_signal"), str):
        signal = data["supervisor_senior_signal"].strip().lower()
        if signal in ("none", "last_author", "corresponding"):
            cfg.supervisor_senior_signal = signal
    fid = _oa_field_id(data.get("supervisor_field"))
    if fid is not None:
        cfg.supervisor_field = fid
    # extra country aliases EXTEND the built-in map (module-level, deliberate:
    # canonical_country/guess_country are used before a Config exists)
    if isinstance(data.get("country_aliases"), dict):
        for canon, variants in data["country_aliases"].items():
            if isinstance(variants, list):
                cur = COUNTRY_ALIASES.setdefault(str(canon), [])
                cur.extend(str(v).lower() for v in variants if str(v))
        _rebuild_alias_lookup()


def _rebuild_alias_lookup() -> None:
    global _ALIAS_LOOKUP
    _ALIAS_LOOKUP = sorted(
        ((variant, canon) for canon, variants in COUNTRY_ALIASES.items()
         for variant in variants),
        key=lambda pair: len(pair[0]), reverse=True,
    )


def resolve_field_arg(name: str) -> tuple[str, Optional[str], Optional[dict]]:
    """Resolve --field NAME to (profile_name, subfield_or_None, profile_dict).

    NAME may be a field PROFILE (fields/<name>.yaml, e.g. 'astronomy') or a
    SUBFIELD of any field profile (e.g. 'ism' of 'astronomy', or 'econometrics'
    of 'economics') — the owning profile is returned so the supervisor finder
    can route to the right source and topic list."""
    profile = load_field_profile(name)
    if profile is not None:
        return name, None, profile
    for pname in list_field_profiles():
        p = load_field_profile(pname)
        subs = (p or {}).get("subfields")
        if isinstance(subs, dict) and name in subs:
            return pname, name, p
    default_profile = load_field_profile(FIELD_PROFILE)
    subfields = ((default_profile or {}).get("subfields")
                 if isinstance((default_profile or {}).get("subfields"), dict)
                 else SUBFIELDS)
    known = ", ".join(sorted(set(list_field_profiles())
                             | set(subfields) | {FIELD_PROFILE}))
    raise SystemExit(f"--field {name!r} is neither a field profile "
                     f"(fields/{name}.yaml) nor a subfield of any profile. "
                     f"Known: {known}")


def build_config(args: argparse.Namespace) -> Config:
    cfg = Config(
        core_anchors=list(CORE_ANCHORS),
        context_terms=list(CONTEXT_TERMS),
        negative_terms=list(NEGATIVE_TERMS),
        weights=dict(RELEVANCE_WEIGHTS),
        threshold=RELEVANCE_THRESHOLD,
        search_terms=list(SEARCH_TERMS),
        countries=list(COUNTRIES),
        wanted_types=list(WANTED_POSITION_TYPES),
        keep_ambiguous=KEEP_AMBIGUOUS,
        sources_enabled=dict(SOURCES_ENABLED),
        output_path=OUTPUT_PATH,
        write_html=WRITE_HTML,
        proxy=PROXY,
        proxy_fallback_direct=PROXY_FALLBACK_DIRECT,
        headed_fallback=HEADED_FALLBACK,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
        backoff=BACKOFF_FACTOR,
        delay=REQUEST_DELAY,
        robots_obey=ROBOTS_OBEY,
        user_agent=USER_AGENT,
        max_desc=MAX_DESC_CHARS,
        exclude_expired=EXCLUDE_EXPIRED,
        strict_phd_only=getattr(args, "phd_only", False),
        debug=bool(getattr(args, "debug", False)),
    )

    # 1) config.yaml (runtime settings) — optional overlay
    if not getattr(args, "no_config", False):
        cfg_path = _find_config_path(CONFIG_FILE)
        if cfg_path:
            data = _load_yaml_file(cfg_path)
            if data:
                apply_config_yaml(cfg, data)
                log.debug("applied runtime config from %s", cfg_path)

    # 2) field profile (taxonomy) — optional overlay; --field may name either
    #    a profile (fields/x.yaml) or a subfield of the default profile
    field_arg = getattr(args, "field", None) or cfg.field_profile
    profile: Optional[dict] = None
    if getattr(args, "field", None):
        cfg.field_profile, cfg.subfield, profile = resolve_field_arg(field_arg)
    else:
        cfg.field_profile = field_arg
        profile = load_field_profile(field_arg)
    if profile:
        apply_field_profile(cfg, profile)
        log.info("field profile '%s' loaded from %s (%d anchors)",
                 cfg.field_profile, profile.get("_path", "?"),
                 len(cfg.core_anchors))
    elif cfg.field_profile != FIELD_PROFILE:
        raise SystemExit(f"field profile fields/{cfg.field_profile}.yaml "
                         "not found")
    else:
        log.debug("no fields/%s.yaml — using built-in astronomy taxonomy",
                  FIELD_PROFILE)

    # 3) CLI overrides (highest priority)
    if getattr(args, "country", None):
        cfg.countries = list(args.country)
    if getattr(args, "keyword", None):
        # extra user keywords become additional CORE anchors
        cfg.core_anchors = cfg.core_anchors + list(args.keyword)
    if getattr(args, "threshold", None) is not None:
        cfg.threshold = float(args.threshold)
    # Env override (packaged sidecar / 12-factor deploys): ASTRA_PROXY sets the
    # proxy without needing config.yaml on disk; an empty value disables it and
    # an explicit --proxy still wins.
    _env_proxy = os.environ.get("ASTRA_PROXY")
    if _env_proxy is not None and getattr(args, "proxy", None) is None:
        cfg.proxy = _env_proxy or None
    if getattr(args, "proxy", None) is not None:
        cfg.proxy = args.proxy or None
    if getattr(args, "no_proxy_detect", False):
        cfg.auto_detect_proxy = False
    if getattr(args, "output", None):
        cfg.output_path = args.output
    if getattr(args, "no_robots", False):
        cfg.robots_obey = False
    if getattr(args, "no_html", False):
        cfg.write_html = False
    if getattr(args, "no_headed", False):
        cfg.headed_fallback = False
    if getattr(args, "include_expired", False):
        cfg.exclude_expired = False
    if getattr(args, "phd_only", False):
        cfg.strict_phd_only = True
    if getattr(args, "browser_profile", None):
        cfg.browser_profile_dir = args.browser_profile
    if getattr(args, "fresh_profile", False):
        import shutil
        shutil.rmtree(cfg.browser_profile_dir, ignore_errors=True)
        log.info("wiped persistent browser profile %s", cfg.browser_profile_dir)
    if getattr(args, "challenge_wait", None) is not None:
        cfg.challenge_wait_ms = max(1000, int(args.challenge_wait))
    if getattr(args, "seeds", None):
        cfg.seed_file = args.seeds
    if getattr(args, "max_age_days", None) is not None:
        cfg.max_age_days = int(args.max_age_days)
    if getattr(args, "years_back", None) is not None:
        cfg.supervisor_years_back = int(args.years_back)
    if getattr(args, "supervisor_source", None):
        cfg.supervisor_source = args.supervisor_source
    if getattr(args, "force_refresh", False):
        cfg.force_refresh = True
    if getattr(args, "no_http_cache", False):
        cfg.http_cache = False
    if getattr(args, "include_slow_sources", False):
        cfg.include_slow_sources = True
    types = getattr(args, "types", None)
    if types:
        # PhD and postdoc are separate searches. Only types the registry
        # actually offers are accepted; a planned-but-disabled one (masters,
        # scholarship) is reported rather than silently returning nothing.
        from core import position_types as _pt
        wanted = [str(x).strip().lower() for x in types if str(x).strip()]
        offered = {x.name for x in _pt.offered_types()}
        unknown = [x for x in wanted if x not in offered]
        if unknown:
            planned = {x.name for x in _pt.coming_soon_types()}
            for name in unknown:
                log.warning("position type %r is %s — ignored", name,
                            "not available yet" if name in planned
                            else "not a known type")
        kept = [x for x in wanted if x in offered]
        if kept:
            cfg.wanted_types = kept
            log.info("hunting position type(s): %s", ", ".join(kept))
    subfields = getattr(args, "subfields", None)
    if subfields:
        apply_subfield_focus(cfg, subfields)
    compile_taxonomy(cfg)
    return cfg


def apply_subfield_focus(cfg: Config, subfield_ids: list[str]) -> list[str]:
    """Narrow a run to some subfields of the active profile — by BOOSTING.

    Selected subfield keywords are appended to ``context_terms``, which by
    definition raise a post's score but can never qualify one on their own.
    That is deliberate: job ads are short and frequently describe a project
    without ever naming its subfield, so a hard filter would throw away good
    positions. Supervisor search does apply these as a real topic filter —
    publication records carry enough text to support one.

    Returns the subfield ids that actually matched the profile; unknown ids are
    reported and skipped rather than silently narrowing the search to nothing.
    """
    known = cfg.subfields if isinstance(cfg.subfields, dict) else {}
    wanted = [str(s).strip() for s in subfield_ids if str(s).strip()]
    matched, unknown, keywords = [], [], []
    for sid in wanted:
        entry = known.get(sid)
        if not isinstance(entry, dict):
            unknown.append(sid)
            continue
        matched.append(sid)
        keywords.extend(str(k) for k in (entry.get("keywords") or [])
                        if str(k).strip())
    if unknown:
        log.warning("subfield(s) %s not found in profile %r — ignored "
                    "(available: %s)", ", ".join(unknown), cfg.field_profile,
                    ", ".join(sorted(known)) or "none")
    if keywords:
        existing = set(cfg.context_terms)
        cfg.context_terms = list(cfg.context_terms) + [
            k for k in dict.fromkeys(keywords) if k not in existing]
        log.info("subfield focus %s: +%d boost terms", ", ".join(matched),
                 len(cfg.context_terms) - len(existing))
    cfg.selected_subfields = matched
    return matched


# Canonical country -> recognised variants (extend freely).
COUNTRY_ALIASES: dict[str, list[str]] = {
    "United Kingdom": ["united kingdom", "uk", "u.k.", "britain", "great britain",
                       "england", "scotland", "wales", "northern ireland"],
    "United States": ["united states", "usa", "u.s.a.", "u.s.", "us", "america"],
    "Germany": ["germany", "deutschland"],
    "Netherlands": ["netherlands", "the netherlands", "holland", "nederland"],
    "France": ["france"],
    "Italy": ["italy", "italia"],
    "Spain": ["spain", "espana", "españa"],
    "Switzerland": ["switzerland", "schweiz", "suisse"],
    "Belgium": ["belgium"],
    "Austria": ["austria", "osterreich", "österreich"],
    "Sweden": ["sweden", "sverige"],
    "Norway": ["norway", "norge"],
    "Denmark": ["denmark"],
    "Finland": ["finland", "suomi"],
    "Ireland": ["ireland", "eire"],
    "Poland": ["poland", "polska"],
    "Portugal": ["portugal"],
    "Czechia": ["czechia", "czech republic"],
    "Hungary": ["hungary"],
    "Greece": ["greece"],
    "Estonia": ["estonia"],
    "Latvia": ["latvia"],
    "Lithuania": ["lithuania"],
    "Slovenia": ["slovenia"],
    "Slovakia": ["slovakia"],
    "Romania": ["romania"],
    "Bulgaria": ["bulgaria"],
    "Croatia": ["croatia"],
    "Serbia": ["serbia"],
    "Turkey": ["turkey", "türkiye", "turkiye"],
    "Russia": ["russia", "russian federation"],
    "Ukraine": ["ukraine"],
    "Iceland": ["iceland"],
    "Luxembourg": ["luxembourg"],
    "Japan": ["japan", "nippon", "nihon"],
    "China": ["china", "p.r. china", "prc", "people's republic of china"],
    "South Korea": ["south korea", "republic of korea", "korea", "rok"],
    "North Korea": ["north korea", "dprk"],
    "Taiwan": ["taiwan"],
    "India": ["india"],
    "Israel": ["israel"],
    "Singapore": ["singapore"],
    "New Zealand": ["new zealand", "aotearoa", "nz"],
    "Australia": ["australia"],
    "Canada": ["canada"],
    "Chile": ["chile"],
    "Brazil": ["brazil", "brasil"],
    "Mexico": ["mexico", "méxico"],
    "Argentina": ["argentina"],
    "South Africa": ["south africa"],
    "Saudi Arabia": ["saudi arabia"],
    "United Arab Emirates": ["united arab emirates", "uae", "abu dhabi", "dubai"],
    "Qatar": ["qatar"],
}
# Reverse lookup, longest variants first so "south korea" beats "korea".
_ALIAS_LOOKUP: list[tuple[str, str]] = sorted(
    ((variant, canon) for canon, variants in COUNTRY_ALIASES.items()
     for variant in variants),
    key=lambda pair: len(pair[0]), reverse=True,
)

# Pristine built-in alias table, captured once at import. apply_config_yaml()
# extends COUNTRY_ALIASES in place; reset_country_aliases() restores this base
# so self-tests / repeated runs are hermetic (see self_test in the monolith).
_COUNTRY_ALIASES_BASE: dict[str, list[str]] = {
    canon: list(variants) for canon, variants in COUNTRY_ALIASES.items()
}


def reset_country_aliases() -> None:
    """Drop any runtime-extended country aliases and restore the built-ins."""
    global _ALIAS_LOOKUP
    COUNTRY_ALIASES.clear()
    COUNTRY_ALIASES.update(
        {canon: list(variants)
         for canon, variants in _COUNTRY_ALIASES_BASE.items()})
    _rebuild_alias_lookup()

# ISO-3166 alpha-2 -> canonical name (job APIs and "(CN)" suffixes use these).
ISO2_COUNTRY: dict[str, str] = {
    "GB": "United Kingdom", "UK": "United Kingdom", "US": "United States",
    "DE": "Germany", "NL": "Netherlands", "FR": "France", "IT": "Italy",
    "ES": "Spain", "CH": "Switzerland", "BE": "Belgium", "AT": "Austria",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "IE": "Ireland", "PL": "Poland", "PT": "Portugal", "CZ": "Czechia",
    "HU": "Hungary", "GR": "Greece", "EE": "Estonia", "LV": "Latvia",
    "LT": "Lithuania", "SI": "Slovenia", "SK": "Slovakia", "RO": "Romania",
    "BG": "Bulgaria", "HR": "Croatia", "RS": "Serbia", "TR": "Turkey",
    "RU": "Russia", "UA": "Ukraine", "IS": "Iceland", "LU": "Luxembourg",
    "JP": "Japan", "CN": "China", "KR": "South Korea", "TW": "Taiwan",
    "IN": "India", "IL": "Israel", "SG": "Singapore", "NZ": "New Zealand",
    "AU": "Australia", "CA": "Canada", "CL": "Chile", "BR": "Brazil",
    "MX": "Mexico", "AR": "Argentina", "ZA": "South Africa",
    "SA": "Saudi Arabia", "AE": "United Arab Emirates", "QA": "Qatar",
}

# Canonical country -> ISO-3166 alpha-2 (for APIs that filter by code, e.g.
# OpenAlex's authorships.countries). First code found wins (GB vs UK -> GB).
_CANON_TO_ISO2: dict[str, str] = {}
for _code, _canon in ISO2_COUNTRY.items():
    _CANON_TO_ISO2.setdefault(_canon, _code)


# -----------------------------------------------------------------------------
# RELEVANCE ENGINE  (compile step — moved to core/taxonomy.py in Step 3; we
# re-import the two names here so build_config + back-compat importers still get
# them from core.config, which __all__ advertises. core.taxonomy imports back
# only type-level Config, keeping the dependency acyclic.)
# -----------------------------------------------------------------------------
from core.taxonomy import _compile_term, compile_taxonomy  # noqa: E402,F401
