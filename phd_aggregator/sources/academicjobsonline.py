"""source_academicjobsonline — AcademicJobsOnline (migration Step 5, Batch A)."""

from __future__ import annotations

import re

from core.config import Config
from core.http import Http
from core.records import make_record

from . import registry
from .base import log, register_source




def ajo_categories_for(cfg: Config) -> list[str]:
    """Category path(s) to sweep for the active profile ([] = skip the board).

    AJO's category paths are its own vocabulary ("cs", "physics/Astrophysics"),
    so they live in sources/url_registry.yaml rather than being derived from
    the field name. A profile's source_options.academicjobsonline.categories
    still wins.
    """
    values = registry.values_for(cfg, "academicjobsonline", "categories")
    return [str(c).strip().strip("/") for c in values if str(c).strip()]


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