"""source_nature_careers — Nature Careers (migration Step 5, Batch B)."""

from __future__ import annotations

import re

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


@register_source("nature_careers")
def source_nature_careers(cfg: Config, http: Http) -> list[dict]:
    """[HTML] Nature Careers (nature.com/naturecareers).

    HTML search at /naturecareers/jobs/?Keywords=X — server-rendered
    lister__item cards; the correct parameter is 'Keywords', not 'q' ('q'
    returns only sponsored listings). A keyword with zero matches returns
    HTTP 404 — that's normal, the pass is just skipped.

    NOTE: nature.com/robots.txt explicitly disallows /naturecareers/jobsrss/
    (their RSS export) and /naturecareers/jobs/search — do not wire those.
    """
    SEARCH_URL = "https://www.nature.com/naturecareers/jobs/"
    LINK_RE = re.compile(r"/naturecareers/job/")

    out: list[dict] = []
    seen: set[str] = set()

    def job_key(url: str) -> str:
        m = re.search(r"/naturecareers/job/(\d+)/", url or "")
        return m.group(1) if m else (url or "")

    # one search pass per term (richer fields: institution, location, closing)
    for kw in cfg.search_terms[:6]:
        soup = http.get_soup(SEARCH_URL, params={"Keywords": kw})
        if not soup:
            continue
        for item in soup.find_all("li", class_="lister__item"):
            link_el = item.find("a", href=LINK_RE)
            if not link_el:
                continue
            href = (link_el["href"] or "").strip()
            url = href if href.startswith("http") else "https://www.nature.com" + href
            k = job_key(url)
            if not k or k in seen:
                continue
            seen.add(k)

            title_el = item.find("h2") or item.find("h3")
            title = (title_el.get_text(strip=True) if title_el
                     else link_el.get_text(strip=True))
            inst_el = item.find(class_=re.compile(r"lister__recruiter|recruiter"))
            institution = inst_el.get_text(strip=True) if inst_el else None
            loc_el = item.find(class_=re.compile(r"lister__location|location"))
            raw_loc = loc_el.get_text(strip=True) if loc_el else None
            desc_el = item.find(class_=re.compile(r"lister__description|description"))
            desc = desc_el.get_text(strip=True) if desc_el else None
            closing_el = item.find(class_=re.compile(r"lister__closing|closing"))
            deadline = closing_el.get_text(strip=True) if closing_el else None

            out.append(make_record(
                title=title, institution=institution, url=url,
                short_description=desc, raw_location=raw_loc,
                deadline=deadline, source="nature_careers",
            ))

    if not out:
        log.warning("[nature_careers] 0 listings — check Keywords param/selectors")
    return out