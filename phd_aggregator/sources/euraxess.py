"""source_euraxess — EURAXESS job portal (migration Step 5, Batch B)."""

from __future__ import annotations

import re
from typing import Optional

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


# EURAXESS `job_research_field` facet IDs, read off the live portal's own facet
# sidebar on 2026-08-14 (the portal ignores plain ?keywords=, so the facet is
# the only way to scope a search). A field profile overrides this with
#     source_options: {euraxess: {research_fields: [47]}}
# and this table is only the fallback for profiles that say nothing.
EURAXESS_RESEARCH_FIELDS: dict[str, list[int]] = {
    "agricultural sciences": [2],
    "astronomy": [34, 35, 37],        # 35/37 = Astrophysics / Astronomy other
    "biological sciences": [38],
    "chemistry": [47],
    "communication sciences": [65],
    "computer science": [78],
    "criminology": [92],
    "cultural studies": [94],
    "demography": [115],
    "economics": [117],
    "educational sciences": [158],
    "engineering": [164],
    "environmental science": [195],
    "geosciences": [219],
    "history": [223],
    "information science": [251],
    "language sciences": [281],
    "literature": [286],
    "mathematics": [298],
    "medical sciences": [313],
    "neurosciences": [317],
    "pharmacological sciences": [325],
    "physics": [345],
    "psychological sciences": [374],
    "religious sciences": [380],
    "sociology": [388],
    "technology": [401],
}

# Profile name -> the EURAXESS subject(s) that discipline lives under. Only
# needed where the two vocabularies disagree; an exact name match wins first.
_PROFILE_TO_EURAXESS = {
    "biology": ["biological sciences"],
    "computer_science": ["computer science", "information science"],
    "condensed_matter": ["physics"],
    "geology": ["geosciences"],
    "geophysics_hydro": ["geosciences", "physics"],
    "medicine": ["medical sciences", "neurosciences",
                 "pharmacological sciences"],
    "psychology": ["psychological sciences"],
    "social_sciences": ["sociology", "demography", "communication sciences"],
    "humanities": ["history", "literature", "language sciences",
                   "cultural studies"],
    "environmental_science": ["environmental science", "geosciences"],
}


def _facet_strings(values) -> list[str]:
    return [f"job_research_field:{int(v)}" for v in (values or [])
            if str(v).strip().isdigit()]


def euraxess_facets_for(cfg: Config) -> list[str]:
    """The `job_research_field:N` facet strings to search for this profile.

    Resolution order: the profile's own ``source_options.euraxess.
    research_fields`` -> the profile-name mapping above -> an exact match on
    the EURAXESS subject list -> ``[]`` (caller falls back to a keyword scan).
    """
    explicit = cfg.source_option("euraxess", "research_fields")
    if isinstance(explicit, list) and explicit:
        return _facet_strings(explicit)

    name = (getattr(cfg, "field_profile", "") or "").strip().lower()
    subjects = _PROFILE_TO_EURAXESS.get(name)
    if subjects is None:
        spaced = name.replace("_", " ")
        subjects = [spaced] if spaced in EURAXESS_RESEARCH_FIELDS else []
    ids = [i for s in subjects for i in EURAXESS_RESEARCH_FIELDS.get(s, [])]
    return _facet_strings(dict.fromkeys(ids))


def euraxess_adjacent_facets_for(cfg: Config) -> list[str]:
    """Neighbouring subjects worth one extra PhD-scoped sweep.

    Astronomy has always also swept the broad Physics facet (345) for PhD
    positions — genuine astro PhDs are filed under Physics often enough to
    matter. That stays true, it is just data now:
    ``source_options: {euraxess: {adjacent_research_fields: [345]}}``.
    """
    return _facet_strings(
        cfg.source_option("euraxess", "adjacent_research_fields"))


@register_source("euraxess", label="EURAXESS (EU)")
def source_euraxess(cfg: Config, http: Http) -> list[dict]:
    """[HTML] EURAXESS (euraxess.ec.europa.eu). The old RSS endpoint is gone
    and the plain ?keywords= parameter is IGNORED by the new portal (it happily
    returns business professorships for 'astrophysics'). The real search uses
    Drupal facet parameters, verified live:

        f[n]=job_research_field:34   Astronomy
        f[n]=job_research_field:35   Astrophysics
        f[n]=job_research_field:37   Astronomy other
        f[n]=job_research_field:345  Physics (broad; relevance engine trims)
        f[n]=positions:php_positions PhD positions  (sic — their code)
        page=N                       0-based pagination, 10 results/page

    Result cards are server-rendered `article.ecl-content-item` elements.
    """
    BASE = "https://euraxess.ec.europa.eu/jobs/search"
    facets = euraxess_facets_for(cfg)
    if not facets:
        # No facet mapping for this discipline: fall back to the PhD-positions
        # facet alone. Broad, but the relevance engine trims it with the
        # profile's own anchors — far better than searching someone else's
        # subject. Add source_options.euraxess.research_fields to fix properly.
        log.info("[euraxess] no research-field facet for profile %r — "
                 "searching all PhD positions and letting the relevance "
                 "engine trim (set source_options.euraxess.research_fields)",
                 getattr(cfg, "field_profile", None))
        QUERIES: list[tuple[list[str], Optional[str], int]] = [
            (["positions:php_positions"], "phd", 4),
        ]
    else:
        log.info("[euraxess] research-field facets for %r: %s",
                 getattr(cfg, "field_profile", None), ", ".join(facets))
        QUERIES = [
            # (facets, forced position_type, max pages)
            (facets, None, 4),                                # all field offers
            (facets + ["positions:php_positions"], "phd", 3),  # field ∩ PhD
        ]
        for adjacent in euraxess_adjacent_facets_for(cfg):
            # One extra PhD-scoped pass per neighbouring subject.
            QUERIES.append(([adjacent, "positions:php_positions"], None, 3))

    out: list[dict] = []
    seen: set[str] = set()
    for facets, forced_type, max_pages in QUERIES:
        for page_no in range(max_pages):
            params = [(f"f[{i}]", f) for i, f in enumerate(facets)]
            if page_no:
                params.append(("page", str(page_no)))
            soup = http.get_soup(BASE, params=params)
            if not soup:
                break
            articles = soup.find_all("article", class_="ecl-content-item")
            if not articles:
                break
            for article in articles:
                try:
                    rec = _euraxess_card(article, forced_type)
                    if rec and rec["url"] not in seen:
                        seen.add(rec["url"])
                        out.append(rec)
                except Exception as exc:
                    log.debug("[euraxess] bad card: %s", exc)
            if len(articles) < 10:
                break  # last page

    if not out:
        log.warning("[euraxess] 0 listings — facet IDs may have changed")
    return out


def _euraxess_card(article, forced_type: Optional[str]) -> Optional[dict]:
    link_el = article.find("a", href=re.compile(r"^/jobs/\d+"))
    if not link_el:
        return None
    href = link_el["href"]
    url = ("https://euraxess.ec.europa.eu" + href
           if href.startswith("/") else href)

    title_el = article.find("h3", class_="ecl-content-block__title")
    title = (title_el.get_text(strip=True) if title_el
             else link_el.get_text(strip=True))

    institution = None
    posted_date = None
    primary_meta = article.find("ul", class_="ecl-content-block__primary-meta-container")
    if primary_meta:
        for li in primary_meta.find_all("li"):
            if li.find("a", href=re.compile(r"/partnering/")):
                institution = li.get_text(strip=True)
            elif "Posted on:" in li.get_text():
                posted_date = li.get_text(strip=True).replace("Posted on:", "").strip()

    desc_el = article.find("div", class_="ecl-content-block__description")
    desc = desc_el.get_text(strip=True) if desc_el else None

    loc_div = article.find("div", class_="id-Work-Locations")
    raw_loc = loc_div.get_text(" ", strip=True) if loc_div else None

    deadline = None
    dl_div = article.find("div", class_="id-Application-Deadline")
    if dl_div:
        t = dl_div.find("time", datetime=True)
        deadline = t["datetime"][:10] if t else dl_div.get_text(" ", strip=True)

    return make_record(
        title=title, institution=institution, url=url,
        posted_date=posted_date, deadline=deadline,
        short_description=desc, raw_location=raw_loc,
        position_type=forced_type, source="euraxess",
    )