"""source_aas — AAS Job Register, Cloudflare-guarded (feed chain then browser
chain). Migration Step 5, Batch C."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core.config import Config
from core.deps import _HTML_PARSER
from core.http import Http
from core.records import make_record

from .base import _feed_records, log, register_source


@register_source("aas")
def source_aas(cfg: Config, http: Http) -> list[dict]:
    """[FEED/JS] AAS Job Register (jobregister.aas.org) — THE astronomy board.

    Cloudflare sits in front of everything. Chain: RSS via requests ->
    curl_cffi browser TLS -> Playwright on the graduate category page ->
    headed browser. Verified 2026-07: some VPN exit IPs are refused even in a
    real browser (IP reputation); the source then logs and skips. Try another
    V2Ray server if you see the 'anti-bot challenge' warning.
    """
    AAS_RSS_URL = "https://jobregister.aas.org/rss"
    # Pre-doctoral/graduate category = where PhD-level posts live.
    AAS_GRAD_URL = "https://jobregister.aas.org/jobs/pre-doctoral-graduate"

    feed = http.get_feed(AAS_RSS_URL,
                         headers={"Referer": "https://jobregister.aas.org/"})
    if feed and getattr(feed, "entries", None):
        return _feed_records(feed, "aas")

    log.info("[aas] RSS blocked — trying a browser on the graduate category")
    html = http.get_rendered(AAS_GRAD_URL,
                             wait_selector="a[href*='/jobs/']",
                             timeout_ms=30000)
    if not html:
        return []
    soup = BeautifulSoup(html, _HTML_PARSER)
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/jobs/\d+")):
        href = a.get("href", "")
        url = href if href.startswith("http") else "https://jobregister.aas.org" + href
        title = a.get_text(" ", strip=True)
        if url in seen or not title:
            continue
        seen.add(url)
        out.append(make_record(title=title, url=url,
                               position_type="phd",  # graduate category page
                               source="aas"))
    if not out:
        log.warning("[aas] 0 listings after browser render")
    return out
