"""source_academicjobsonline — AcademicJobsOnline (migration Step 5, Batch A)."""

from __future__ import annotations

import re

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


# AcademicJobsOnline category slugs, each verified live on 2026-08-14 by
# fetching https://academicjobsonline.org/ajo/<slug> and counting job links
# (chemistry 26, biology 44, cs 47, mathematics/economics/psychology/medicine/
# engineering/statistics 40 each). A field profile overrides this with
#     source_options: {academicjobsonline: {categories: [chemistry]}}
AJO_CATEGORIES: dict[str, list[str]] = {
    "astronomy": ["physics/Astronomy", "physics/Astrophysics"],
    "physics": ["physics"],
    "condensed_matter": ["physics"],
    "chemistry": ["chemistry"],
    "biology": ["biology"],
    "computer_science": ["cs"],
    "mathematics": ["mathematics", "statistics"],
    "engineering": ["engineering"],
    "economics": ["economics"],
    "psychology": ["psychology"],
    "medicine": ["medicine"],
    "geology": ["geosciences"],
    "geophysics_hydro": ["geosciences"],
}


def ajo_categories_for(cfg: Config) -> list[str]:
    """Category path(s) to sweep for the active profile ([] = skip the board)."""
    explicit = cfg.source_option("academicjobsonline", "categories")
    if isinstance(explicit, list) and explicit:
        return [str(c).strip().strip("/") for c in explicit if str(c).strip()]
    name = (getattr(cfg, "field_profile", "") or "").strip().lower()
    return list(AJO_CATEGORIES.get(name, []))


@register_source("academicjobsonline", label="AcademicJobsOnline")
def source_academicjobsonline(cfg: Config, http: Http) -> list[dict]:
    """[HTML] AcademicJobsOnline (academicjobsonline.org). Category pages are
    server-rendered; robots.txt asks for a 5s crawl delay (honored). Each
    institution appears as an <h3 class="x1"> heading followed by an <ol> of
    job <li>s shaped like: [CODE] Title (deadline YYYY/MM/DD ...) Apply
    """
    categories = ajo_categories_for(cfg)
    if not categories:
        log.info("[academicjobsonline] no category mapping for profile %r — "
                 "skipping (set source_options.academicjobsonline.categories "
                 "in fields/%s.yaml)", getattr(cfg, "field_profile", None),
                 getattr(cfg, "field_profile", "<profile>"))
        return []
    CATEGORY_URLS = [f"https://academicjobsonline.org/ajo/{c}"
                     for c in categories]
    log.info("[academicjobsonline] categories for %r: %s",
             getattr(cfg, "field_profile", None), ", ".join(categories))
    LINK_RE = re.compile(r"^/ajo/jobs?/(\d+)$")

    out: list[dict] = []
    seen: set[str] = set()

    for cat_url in CATEGORY_URLS:
        soup = http.get_soup(cat_url)
        if not soup:
            continue
        for a in soup.find_all("a", href=LINK_RE):
            href = a["href"]
            url = ("https://academicjobsonline.org" + href
                   if href.startswith("/") else href)
            if url in seen:
                continue
            seen.add(url)

            li = a.find_parent("li")
            institution = None
            ol = a.find_parent("ol")
            if ol:
                h3 = ol.find_previous("h3")
                if h3:
                    institution = h3.get_text(" ", strip=True)
            if li:
                li_text = li.get_text(" ")
                title_m = re.match(r"\[([^\]]+)\]\s*(.*?)(?:\s*\(deadline|\s*$)",
                                   li_text.strip())
                title = title_m.group(2).strip() if title_m else a.get_text(" ")
                dl_m = re.search(r"deadline\s+([\d/]+)", li_text, re.I)
                deadline = dl_m.group(1).replace("/", "-") if dl_m else None
            else:
                title = a.get_text(" ")
                deadline = None

            out.append(make_record(title=title, institution=institution,
                                   url=url, deadline=deadline,
                                   source="academicjobsonline"))

    if not out:
        log.warning("[academicjobsonline] 0 listings — check category URLs")
    return out