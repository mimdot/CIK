"""source_jobs_ac_uk — jobs.ac.uk PhD facet search (migration Step 5, Batch B)."""

from __future__ import annotations

from datetime import date

from core.config import Config
from core.http import Http
from core.records import make_record
from core.utils import parse_date

from .base import log, register_source


@register_source("jobs_ac_uk", label="jobs.ac.uk (UK)")
def source_jobs_ac_uk(cfg: Config, http: Http) -> list[dict]:
    """[HTML] jobs.ac.uk (UK). RSS export was removed; the search results are
    server-rendered. jobTypeFacet[]=phds narrows to PhD studentships (verified
    live). Department names ("Dept of Physics & Astronomy") are kept OUT of the
    scored description — they caused diode-laser PhDs to match 'astronomy'.
    """
    SEARCH_URL = "https://www.jobs.ac.uk/search/"

    out: list[dict] = []
    seen: set[str] = set()
    today_year = date.today().year

    queries = [[("keywords", kw), ("jobTypeFacet[]", "phds"),
                ("pageSize", "50")] for kw in cfg.search_terms[:4]]

    for params in queries:
        soup = http.get_soup(SEARCH_URL, params=params)
        if not soup:
            continue
        for container in soup.find_all("div", class_="j-search-result__result"):
            text_div = container.find("div", class_="j-search-result__text")
            date_div = container.find("div", class_="j-search-result__date-logos")
            if not text_div:
                continue
            link_el = text_div.find("a", href=True)
            if not link_el:
                continue
            href = link_el["href"]
            url = "https://www.jobs.ac.uk" + href if href.startswith("/") else href
            if url in seen:
                continue
            seen.add(url)
            title = link_el.get_text(strip=True)

            inst_el = text_div.find("div", class_="j-search-result__employer")
            institution = inst_el.get_text(strip=True) if inst_el else None
            dept_el = text_div.find("div", class_="j-search-result__department")
            dept = dept_el.get_text(strip=True) if dept_el else None

            # Closing date is in a blue span: e.g. "23 Jun" (year implied)
            deadline = None
            if date_div:
                blue = date_div.find("span", class_="j-search-result__date--blue")
                if blue:
                    raw = blue.get_text(strip=True)
                    for yr in (today_year, today_year + 1):
                        d = parse_date(f"{raw} {yr}")
                        if d:
                            deadline = d
                            if d >= date.today().isoformat():
                                break

            out.append(make_record(
                title=title,
                institution=(f"{institution} ({dept})" if institution and dept
                             else institution or dept),
                country="United Kingdom",   # board default; card text may override
                deadline=deadline,
                url=url,
                # full card text feeds country detection ("Aarhus", "Denmark",
                # "Munich" ...) without polluting the scored description
                raw_location=container.get_text(" ", strip=True),
                # dept deliberately NOT in short_description (not scored)
                position_type="phd",     # guaranteed by jobTypeFacet=phds
                source="jobs_ac_uk",
            ))

    if not out:
        log.warning("[jobs_ac_uk] 0 listings — selectors may need updating")
    return out