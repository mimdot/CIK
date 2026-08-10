"""source_linkedin — LinkedIn Jobs via the public guest search endpoint
(migration Step 5, Batch C). No login, no evasion; robots.txt overridden for
a handful of personal-use queries."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from core.config import Config
from core.deps import _HTML_PARSER
from core.http import Http
from core.records import make_record

from .base import log, register_source

# LinkedIn guest job search (the JSON-less HTML fragment endpoint the public
# /jobs/search page itself calls before login). Free-text `location` works;
# `start` pages by 25. Endpoint + selectors verified live July 2026.
LINKEDIN_GUEST_URL = ("https://www.linkedin.com/jobs-guest/jobs/api/"
                      "seeMoreJobPostings/search")
LINKEDIN_KEYWORDS = ["PhD astronomy", "PhD astrophysics", "PhD cosmology",
                     "doctoral researcher astrophysics"]
LINKEDIN_LOCATIONS = ["European Union", "United Kingdom", "Japan", "China"]
LINKEDIN_MAX_PAGES = 1          # pages of 25 per (keyword, location) pair


@register_source("linkedin")
def source_linkedin(cfg: Config, http: Http) -> list[dict]:
    """[HTML] LinkedIn Jobs via the public guest search endpoint (no login).

    NOTE: LinkedIn's User Agreement prohibits automated access, and its
    robots.txt disallows generic bots — this source therefore makes only a
    handful of low-volume, throttled queries (the same requests your browser
    makes on the public, logged-out jobs page) for PERSONAL job hunting, and
    sets `ignore_robots` for them explicitly. Disable in SOURCES_ENABLED if
    you are not comfortable with that. No login, no evasion: if LinkedIn
    answers 429/999 the source logs it and moves on.
    """
    records: list[dict] = []
    seen_urls: set[str] = set()
    locations = (cfg.countries if cfg.geo_filter_active else LINKEDIN_LOCATIONS)
    log.info("[linkedin] guest search: %d keywords x %d locations "
             "(robots.txt overridden for these personal-use queries)",
             len(LINKEDIN_KEYWORDS), len(locations))

    for loc in locations:
        for kw in LINKEDIN_KEYWORDS:
            for page in range(LINKEDIN_MAX_PAGES):
                params = {"keywords": kw, "location": loc, "start": page * 25}
                resp = http.get(LINKEDIN_GUEST_URL, params=params,
                                ignore_robots=True)
                if resp is None:
                    log.warning("[linkedin] no answer for %r @ %r (rate limit "
                                "or block) — moving on", kw, loc)
                    break
                try:
                    soup = BeautifulSoup(resp.text, _HTML_PARSER)
                except Exception as exc:
                    log.debug("[linkedin] parse failed: %s", exc)
                    break
                cards = soup.select("div.base-card, li div.base-search-card")
                if not cards:
                    break  # empty page = end of results for this query
                for card in cards:
                    rec = _linkedin_card(card)
                    if rec and rec["url"] not in seen_urls:
                        seen_urls.add(rec["url"])
                        records.append(rec)
    log.info("[linkedin] %d unique job cards", len(records))
    return records


# LinkedIn is flooded with contractor/AI-training gigs aimed at PhD HOLDERS
# ("PhD peer review need", "$90/hr remote", "expert annotator") — these are
# not doctoral positions and are dropped at the card level.
_LINKEDIN_GIG_RE = re.compile(
    r"peer.?review|/\s?hr\b|per hour|hourly|freelance|annotat|ai train|"
    r"data label|tutor|expert network|consult|qa lead|part.?time", re.I)


def _linkedin_card(card) -> Optional[dict]:
    """One guest-search result card -> normalized record (defensive)."""
    a = card.select_one("a.base-card__full-link[href]") or card.select_one("a[href]")
    title_el = card.select_one("h3.base-search-card__title") or card.select_one("h3")
    if not a or not title_el:
        return None
    if _LINKEDIN_GIG_RE.search(title_el.get_text(" ", strip=True)):
        return None
    url = a["href"].split("?", 1)[0]           # strip tracking params
    org_el = card.select_one("h4.base-search-card__subtitle")
    loc_el = card.select_one("span.job-search-card__location")
    time_el = card.select_one("time[datetime]")
    raw_loc = loc_el.get_text(" ", strip=True) if loc_el else None
    country = None
    if raw_loc and "," in raw_loc:             # "Bonn, NRW, Germany" -> Germany
        country = raw_loc.rsplit(",", 1)[-1].strip()
    return make_record(
        title=title_el.get_text(" ", strip=True),
        institution=org_el.get_text(" ", strip=True) if org_el else None,
        country=country,
        posted_date=time_el.get("datetime") if time_el else None,
        url=url,
        source="linkedin",
        short_description=None,                # guest cards carry no ad text
        raw_location=raw_loc,
    )
