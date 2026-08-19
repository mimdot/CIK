"""core.utils — defensive text / date / country / URL normalization helpers.

Extracted verbatim from astra.py (migration Step 2). Pure relocation:
no behavior, signature, or output changes.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

import core.config as _core_config
from core.config import ISO2_COUNTRY
from core.deps import _HTML_PARSER


def _strip_html(value: Optional[str]) -> str:
    """Return plain text from a possibly-HTML string."""
    if not value:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        try:
            text = BeautifulSoup(text, _HTML_PARSER).get_text(" ")
        except Exception:
            pass
    return text


def clean_oneline(value: Optional[str]) -> Optional[str]:
    """Collapse whitespace + strip tags into a single clean line."""
    text = _strip_html(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def clean_text(value: Optional[str], max_len: int) -> Optional[str]:
    """Plain-text, whitespace-collapsed, truncated description."""
    text = clean_oneline(value)
    if not text:
        return None
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _slugify(text: Optional[str], max_len: int = 60) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", (text or "")).strip("-").lower()
    return s[:max_len].rstrip("-") or "position"


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y.%m.%d",
)

# Regexes that pull a date out of noisy strings ("Closes: 15th July 2026 (GMT)")
_DATE_EXTRACT = [
    # 2026-07-15 / 2026/7/5 / 2026.07.15 / 2026年07月15日
    (re.compile(r"(\d{4})[年/.\-](\d{1,2})[月/.\-](\d{1,2})日?"), ("y", "m", "d")),
    # 15 July 2026 / 15th Jul 2026
    (re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})"),
     ("d", "bm", "y")),
    # July 15, 2026 / Jul 15 2026
    (re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"),
     ("bm", "d", "y")),
    # 15.07.2026 / 15/07/2026 (day-first; European boards)
    (re.compile(r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})"), ("d", "m", "y")),
]

_DATE_LABEL = re.compile(
    r"^(closing date|closes on|closes|close[sd]?|deadline|apply by|"
    r"application deadline|applications? (?:close|due)|due date|expires?)"
    r"[:\s\-]*", re.I)


def _month_num(token: str) -> Optional[int]:
    for fmt in ("%b", "%B"):
        try:
            return datetime.strptime(token[:3 if fmt == "%b" else None], fmt).month
        except Exception:
            continue
    return None


def parse_date(value) -> Optional[str]:
    """Parse many date shapes into ISO 'YYYY-MM-DD'. Returns None if hopeless.

    Accepts: None, time.struct_time (feedparser), datetime/date, or str.
    """
    if value is None:
        return None
    if isinstance(value, time.struct_time):
        try:
            return time.strftime("%Y-%m-%d", value)
        except Exception:
            return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    text = _DATE_LABEL.sub("", text).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:32], fmt).date().isoformat()
        except ValueError:
            continue
    # Pull a date-ish token out of noisier strings.
    for rx, order in _DATE_EXTRACT:
        m = rx.search(text)
        if not m:
            continue
        parts = dict(zip(order, m.groups()))
        try:
            year = int(parts["y"])
            month = (_month_num(parts["bm"]) if "bm" in parts
                     else int(parts["m"]))
            day = int(parts["d"])
            if month and 2000 <= year <= 2100:
                return date(year, month, day).isoformat()
        except Exception:
            continue
    # Last resort: let pandas try (handles many locale variants).
    try:
        import pandas as pd
        ts = pd.to_datetime(text, errors="coerce")
        if ts is not None and not pd.isna(ts):
            iso = ts.date().isoformat()
            if "2000-01-01" <= iso <= "2100-12-31":
                return iso
    except Exception:
        pass
    return None


def canonical_country(value: Optional[str]) -> Optional[str]:
    """Map a free-form country string (or ISO2 code) to a canonical name.

    Exact alias match wins; if none matches, this deliberately FALLS THROUGH to
    :func:`guess_country`, which does whole-word substring scanning (so a
    fragment such as "united" resolves to "United States"). That fuzzy fallback
    is intentional for messy job-board location strings — exact canonicalization
    is NOT promised."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 2 and text.upper() in ISO2_COUNTRY:
        return ISO2_COUNTRY[text.upper()]
    lowered = text.lower()
    # Read _ALIAS_LOOKUP module-qualified: rebuild_alias_lookup() reassigns it.
    # The hand-written map wins so any user-added country_aliases keep working.
    for variant, canon in _core_config._ALIAS_LOOKUP:
        if lowered == variant:
            return canon
    # Phase 2D: the full ISO-3166 table (249 countries, every code, plus
    # colloquial aliases and misspelling tolerance). The old path knew 53
    # countries and nothing else; anything outside that list silently became
    # "Unknown" and grouped wrongly.
    try:
        from core.normalize import normalize_country
        resolved = normalize_country(text)
        if resolved:
            return resolved
    except Exception:  # normalisation must never break a crawl
        pass
    return guess_country(lowered)  # fuzzy substring match as a last resort


# Major university/research cities that job boards cite WITHOUT a country
# ("Aarhus", "Munich", "Garching" ...). Scanned after COUNTRY_ALIASES, so a
# real country name in the text always wins.
CITY_HINTS: dict[str, str] = {
    "aarhus": "Denmark", "copenhagen": "Denmark", "lyngby": "Denmark",
    "munich": "Germany", "garching": "Germany", "bonn": "Germany",
    "heidelberg": "Germany", "hamburg": "Germany", "berlin": "Germany",
    "potsdam": "Germany", "cologne": "Germany", "koeln": "Germany",
    "leipzig": "Germany", "stuttgart": "Germany", "jena": "Germany",
    "vienna": "Austria", "zurich": "Switzerland", "geneva": "Switzerland",
    "lausanne": "Switzerland", "basel": "Switzerland", "bern": "Switzerland",
    "stockholm": "Sweden", "uppsala": "Sweden", "lund": "Sweden",
    "gothenburg": "Sweden", "oslo": "Norway", "trondheim": "Norway",
    "bergen": "Norway", "helsinki": "Finland", "turku": "Finland",
    "dublin": "Ireland", "edinburgh": "United Kingdom",
    "glasgow": "United Kingdom", "oxford": "United Kingdom",
    "cambridge": "United Kingdom", "manchester": "United Kingdom",
    "bristol": "United Kingdom", "leeds": "United Kingdom",
    "cardiff": "United Kingdom", "york": "United Kingdom",
    "rotterdam": "Netherlands", "amsterdam": "Netherlands",
    "leiden": "Netherlands", "delft": "Netherlands", "eindhoven": "Netherlands",
    "groningen": "Netherlands", "utrecht": "Netherlands",
    "milan": "Italy", "turin": "Italy", "trieste": "Italy",
    "bologna": "Italy", "padua": "Italy", "naples": "Italy",
    "madrid": "Spain", "barcelona": "Spain", "granada": "Spain",
    "valencia": "Spain", "lisbon": "Portugal", "porto": "Portugal",
    "brussels": "Belgium", "gent": "Belgium", "leuven": "Belgium",
    "tokyo": "Japan", "kyoto": "Japan", "osaka": "Japan",
    "tsukuba": "Japan", "sendai": "Japan", "nagoya": "Japan",
    "beijing": "China", "shanghai": "China", "nanjing": "China",
    "hefei": "China", "seoul": "South Korea", "daejeon": "South Korea",
    "busan": "South Korea",     "sydney": "Australia", "melbourne": "Australia",
    "canberra": "Australia", "montreal": "Canada", "toronto": "Canada",
    "vancouver": "Canada", "boston": "United States",
    "princeton": "United States", "pasadena": "United States",
    "new york": "United States", "san francisco": "United States",
    "berkeley": "United States", "palo alto": "United States",
    "los angeles": "United States", "san diego": "United States",
    "champaign": "United States", "ann arbor": "United States",
    "santiago": "Chile", "rio de janeiro": "Brazil", "sao paulo": "Brazil",
    "tel aviv": "Israel", "haifa": "Israel", "singapore": "Singapore",
    "hong kong": "China", "auckland": "New Zealand", "wellington": "New Zealand",
    "prague": "Czechia", "warsaw": "Poland", "cracow": "Poland",
    "budapest": "Hungary", "athens": "Greece", "istanbul": "Turkey",
    "cairo": "Egypt", "moscow": "Russia", "kiev": "Ukraine",
}

# Longest city names first so "rio de janeiro" beats "rio" etc.
_CITY_LOOKUP: list[tuple[str, str]] = sorted(
    ((city, canon) for city, canon in CITY_HINTS.items()),
    key=lambda pair: len(pair[0]), reverse=True,
)


def guess_country(text: Optional[str]) -> Optional[str]:
    """Scan free text for a known country name (whole-word, longest-first),
    then for a well-known city name (CITY_HINTS), then a trailing (XX) code."""
    if not text:
        return None
    lowered = str(text).lower()
    for variant, canon in _core_config._ALIAS_LOOKUP:
        if re.search(r"\b" + re.escape(variant) + r"\b", lowered):
            return canon
    for city, canon in _CITY_LOOKUP:
        if re.search(r"\b" + re.escape(city) + r"\b", lowered):
            return canon
    # Trailing "(CN)"-style ISO2 codes, common in job-board location strings.
    m = re.search(r"\(([A-Z]{2})\)", str(text))
    if m and m.group(1) in ISO2_COUNTRY:
        return ISO2_COUNTRY[m.group(1)]
    return None


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL for dedupe: lowercase scheme/host, drop fragment and
    tracking params, strip trailing slash.

    KNOWN LIMITATION: the drop-set includes the bare param name ``source``.
    A handful of job boards use ``?source=`` as a *semantic* (non-tracking)
    parameter, so two URLs that differ only by it will normalize to the same
    dedupe key. Keeping it in the drop-set is a deliberate behavior choice for
    this migration — do not remove it without a data-quality review of the
    boards that emit ``?source=``."""
    if not url:
        return None
    try:
        p = urlparse(url.strip())
    except Exception:
        return None
    if not p.netloc:
        return None
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "fbclid", "gclid", "ref", "src", "source",
            "linksource"}
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if k.lower() not in drop])
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))


def _key_text(value: Optional[str]) -> str:
    """Aggressively normalize text for the dedupe key."""
    text = clean_oneline(value) or ""
    text = re.sub(r"[^0-9a-z\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def dedupe_key(record: dict) -> tuple:
    """Best-available dedupe key. Prefers title+institution (catches the same
    job posted on several boards), falls back to normalized URL, then title."""
    title = _key_text(record.get("title"))
    inst = _key_text(record.get("institution"))
    if title and inst:
        return ("ti", title, inst)
    url = normalize_url(record.get("url"))
    if url:
        return ("url", url)
    if title:
        return ("t", title)
    return ("id", id(record))  # nothing reliable -> never merge