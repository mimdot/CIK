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


# FindAPhD discipline listing slugs (https://www.findaphd.com/phds/<slug>/).
#
# UNVERIFIED, and honestly so: on 2026-08-14 Cloudflare returned 403 "Just a
# moment..." for EVERY slug from this exit IP — including the two astronomy
# ones that have always shipped. Probing harder would mean working around the
# challenge, which this project does not do: it skips and logs instead. These
# slugs follow FindAPhD's documented URL scheme; a profile can correct any of
# them without a code change:
#     source_options: {findaphd: {disciplines: [chemistry]}}
FINDAPHD_DISCIPLINES: dict[str, list[str]] = {
    "astronomy": ["astrophysics", "astronomy"],
    "physics": ["physics"],
    "condensed_matter": ["physics"],
    "chemistry": ["chemistry"],
    "biology": ["biological-sciences"],
    "computer_science": ["computer-science"],
    "mathematics": ["mathematics"],
    "engineering": ["engineering"],
    "economics": ["economics"],
    "psychology": ["psychology"],
    "medicine": ["medicine"],
    "geology": ["geology"],
    "geophysics_hydro": ["geology"],
}


def findaphd_disciplines_for(cfg: Config) -> list[str]:
    """Listing slug(s) to sweep for the active profile ([] = skip the board)."""
    explicit = cfg.source_option("findaphd", "disciplines")
    if isinstance(explicit, list) and explicit:
        return [str(d).strip().strip("/") for d in explicit if str(d).strip()]
    name = (getattr(cfg, "field_profile", "") or "").strip().lower()
    return list(FINDAPHD_DISCIPLINES.get(name, []))


@register_source("findaphd", label="FindAPhD")
def source_findaphd(cfg: Config, http: Http) -> list[dict]:
    """[JS] FindAPhD (findaphd.com). Cloudflare-protected: plain GET and even
    browser-TLS clients get the JS challenge, so this goes straight to the
    Playwright chain (headless -> headed). Discipline listing pages are used
    instead of keyword search — every hit is a PhD project by definition.

    NOTE: on some VPN exit IPs Cloudflare refuses even a real browser. The
    source then logs and skips; switching the V2Ray server usually fixes it.
    """
    disciplines = findaphd_disciplines_for(cfg)
    if not disciplines:
        log.info("[findaphd] no discipline mapping for profile %r — skipping "
                 "(set source_options.findaphd.disciplines)",
                 getattr(cfg, "field_profile", None))
        return []
    LISTING_URLS = [f"https://www.findaphd.com/phds/{d}/"
                    for d in disciplines]
    log.info("[findaphd] disciplines for %r: %s",
             getattr(cfg, "field_profile", None), ", ".join(disciplines))
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
