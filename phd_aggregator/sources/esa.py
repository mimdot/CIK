"""source_esa — ESA careers (migration Step 5, Batch A)."""

from __future__ import annotations

import re

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


# ESA sites -> country (job cards only show the city).
_ESA_SITES = {
    "noordwijk": "Netherlands", "estec": "Netherlands",
    "frascati": "Italy", "esrin": "Italy",
    "darmstadt": "Germany", "esoc": "Germany", "cologne": "Germany",
    "madrid": "Spain", "villanueva": "Spain", "esac": "Spain",
    "paris": "France", "toulouse": "France",
    "harwell": "United Kingdom", "ecsat": "United Kingdom",
    "redu": "Belgium", "kourou": "France",
}


@register_source("esa")
def source_esa(cfg: Config, http: Http) -> list[dict]:
    """[HTML] ESA careers (jobs.esa.int, SuccessFactors). Search results are
    server-rendered; job links carry class 'jobTitle-link' (verified live).
    ESA offers few true PhD posts (mostly YGT/Research Fellow = postdoc), but
    occasional doctoral openings do appear; the gate sorts them out.
    Astronomy-word queries often return zero on ESA, so broader terms are
    used and the relevance engine does the trimming.
    """
    SEARCH_URL = "https://jobs.esa.int/search/"
    ESA_QUERIES = ["PhD", "science"]
    out: list[dict] = []
    seen: set[str] = set()
    for kw in ESA_QUERIES:
        soup = http.get_soup(SEARCH_URL, params={"q": kw})
        if not soup:
            continue
        for a in soup.find_all("a", class_=re.compile(r"jobTitle")):
            href = a.get("href", "")
            url = "https://jobs.esa.int" + href if href.startswith("/") else href
            if url in seen or not a.get_text(strip=True):
                continue
            seen.add(url)
            title = a.get_text(" ", strip=True)

            country = None
            row = a.find_parent("div", class_=re.compile(r"job-tile|job-row|job\b"))
            row_text = row.get_text(" ", strip=True) if row else ""
            low = (title + " " + row_text).lower()
            for site, c in _ESA_SITES.items():
                if site in low:
                    country = c
                    break

            out.append(make_record(
                title=title, institution="European Space Agency",
                country=country, url=url,
                short_description=row_text[:250] or None,
                source="esa",
            ))
    if not out:
        log.warning("[esa] 0 listings — selector drift?")
    return out