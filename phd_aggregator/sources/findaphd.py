"""source_findaphd — FindAPhD via the Playwright browser chain (migration Step 5,
Batch C). Cloudflare-guarded; PhD-only by definition."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core.config import Config
from core.deps import _HTML_PARSER
from core.http import Http
from core.records import make_record

from .base import log, register_source


@register_source("findaphd", label="FindAPhD")
def source_findaphd(cfg: Config, http: Http) -> list[dict]:
    """[JS] FindAPhD (findaphd.com). Cloudflare-protected: plain GET and even
    browser-TLS clients get the JS challenge, so this goes straight to the
    Playwright chain (headless -> headed). Discipline listing pages are used
    instead of keyword search — every hit is a PhD project by definition.

    NOTE: on some VPN exit IPs Cloudflare refuses even a real browser. The
    source then logs and skips; switching the V2Ray server usually fixes it.
    """
    LISTING_URLS = [
        "https://www.findaphd.com/phds/astrophysics/",
        "https://www.findaphd.com/phds/astronomy/",
    ]
    LINK_RE = re.compile(r"/phds/project/")

    out: list[dict] = []
    seen: set[str] = set()

    for listing in LISTING_URLS:
        html = http.get_rendered(listing,
                                 wait_selector="a[href*='/phds/project/']",
                                 timeout_ms=30000)
        if not html:
            continue
        soup = BeautifulSoup(html, _HTML_PARSER)
        for a in soup.find_all("a", href=LINK_RE):
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 15:
                continue  # icon / "More details" links
            href = a["href"]
            url = href if href.startswith("http") else "https://www.findaphd.com" + href
            url = url.split("?")[0]
            if url in seen:
                continue
            seen.add(url)

            institution = None
            deadline = None
            desc = None
            card = a.find_parent("div", class_=re.compile(r"result|card|listing", re.I))
            if card:
                card_text = card.get_text(" ", strip=True)
                m = re.search(r"(?:Application )?Deadline[:\s]+([A-Za-z0-9 ,/]+?)"
                              r"(?:\s{2,}|$|[|•])", card_text)
                if m:
                    deadline = m.group(1)
                inst_el = card.find("a", href=re.compile(r"/phds/[a-z-]+/(university|centre)", re.I))
                if inst_el:
                    institution = inst_el.get_text(strip=True)
                desc = card_text[:300]

            out.append(make_record(
                title=title, institution=institution, url=url,
                deadline=deadline, short_description=desc,
                position_type="phd",       # FindAPhD lists PhD projects only
                source="findaphd",
            ))

    if not out:
        log.warning("[findaphd] 0 listings (Cloudflare block or selector drift)")
    return out
