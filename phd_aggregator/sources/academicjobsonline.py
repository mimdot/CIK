"""source_academicjobsonline — AcademicJobsOnline (migration Step 5, Batch A)."""

from __future__ import annotations

import re

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


@register_source("academicjobsonline")
def source_academicjobsonline(cfg: Config, http: Http) -> list[dict]:
    """[HTML] AcademicJobsOnline (academicjobsonline.org). Category pages are
    server-rendered; robots.txt asks for a 5s crawl delay (honored). Each
    institution appears as an <h3 class="x1"> heading followed by an <ol> of
    job <li>s shaped like: [CODE] Title (deadline YYYY/MM/DD ...) Apply
    """
    CATEGORY_URLS = [
        "https://academicjobsonline.org/ajo/physics/Astronomy",
        "https://academicjobsonline.org/ajo/physics/Astrophysics",
    ]
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