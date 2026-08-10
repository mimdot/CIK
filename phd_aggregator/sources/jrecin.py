"""source_jrecin — JREC-IN Portal (Japan) (migration Step 5, Batch A)."""

from __future__ import annotations

import re

from core.config import Config
from core.http import Http
from core.records import make_record

from .base import log, register_source


@register_source("jrecin")
def source_jrecin(cfg: Config, http: Http) -> list[dict]:
    """[HTML] JREC-IN Portal (Japan). The search form submits a plain GET to
    /seek/SeekJorSearch (verified live — the old CSRF/Playwright dance is no
    longer needed). English UI via ln=1. Result cards are div.card blocks:
    h5.card_title_min holds the title link; the card text carries
    'Date of update : YYYY/MM/DD' and 'End date of accepting applications :
    YYYY/MM/DD'. Country is always Japan.
    """
    SEARCH_URL = "https://jrecin.jst.go.jp/seek/SeekJorSearch"

    out: list[dict] = []
    seen: set[str] = set()

    for kw in cfg.search_terms[:3]:
        soup = http.get_soup(SEARCH_URL,
                             params={"fn": "1", "ln": "1", "keyword_and": kw})
        if not soup:
            continue
        for card in soup.find_all("div", class_="card"):
            a = card.find("a", href=re.compile(r"SeekJorDetail"))
            if not a:
                continue
            href = a.get("href", "")
            url = "https://jrecin.jst.go.jp" + href if href.startswith("/") else href
            if url in seen:
                continue
            seen.add(url)

            title = a.get_text(strip=True)
            text = card.get_text(" ", strip=True)

            deadline = None
            m = re.search(r"End date of accepting applications\s*[:：]\s*"
                          r"(\d{4}/\d{2}/\d{2})", text)
            if m:
                deadline = m.group(1)
            m2 = re.search(r"Date of update\s*[:：]\s*(\d{4}/\d{2}/\d{2})", text)
            posted = m2.group(1) if m2 else None
            # Japanese-UI fallbacks
            if not deadline:
                m = re.search(r"募集終了日\s*[：:]\s*(\d{4})年(\d{2})月(\d{2})日", text)
                if m:
                    deadline = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

            # institution: the line right after the title inside the card body
            institution = None
            h5 = card.find("h5")
            if h5:
                nxt = h5.find_next(["p", "div", "span"])
                if nxt:
                    cand = nxt.get_text(" ", strip=True)
                    if cand and cand != title and len(cand) < 120:
                        institution = cand

            # keep the level text visible to the classifier via description
            lvl = None
            mlvl = re.search(r"(Graduate student|Researcher/Postdoc level|"
                             r"Assistant Professor level|Professor level"
                             r"[^|]*)", text)
            if mlvl:
                lvl = mlvl.group(1)

            out.append(make_record(
                title=title, institution=institution, country="Japan",
                url=url, deadline=deadline, posted_date=posted,
                short_description=lvl, source="jrecin",
            ))

    if not out:
        log.warning("[jrecin] 0 results — search params or markup drifted")
    return out