"""source_euraxess — EURAXESS job portal (migration Step 5, Batch B)."""

from __future__ import annotations

import re
from typing import Optional

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


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
    ASTRO = ["job_research_field:34", "job_research_field:35",
             "job_research_field:37"]
    QUERIES: list[tuple[list[str], Optional[str], int]] = [
        # (facets, forced position_type, max pages)
        (ASTRO, None, 4),                                   # all astro offers
        (ASTRO + ["positions:php_positions"], "phd", 3),    # astro ∩ PhD
        (["job_research_field:345", "positions:php_positions"], None, 3),
    ]

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