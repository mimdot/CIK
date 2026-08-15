"""source_aas — AAS Job Register, Cloudflare-guarded (feed chain then browser
chain). Migration Step 5, Batch C."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core.config import Config
from core.deps import _HTML_PARSER
from core.http import Http
from core.records import make_record

from . import registry
from .base import _feed_records, log, register_source


@register_source(
    "aas", fields=("astronomy",),
    label="AAS Job Register",
    note="The American Astronomical Society board — astronomy/astrophysics only.")
def source_aas(cfg: Config, http: Http) -> list[dict]:
    """[FEED/JS] AAS Job Register (jobregister.aas.org) — THE astronomy board.

    Cloudflare sits in front of everything. Chain: RSS via requests ->
    curl_cffi browser TLS -> Playwright on the graduate category page ->
    headed browser. Verified 2026-07: some VPN exit IPs are refused even in a
    real browser (IP reputation); the source then logs and skips. Try another
    V2Ray server if you see the 'anti-bot challenge' warning.
    """
    AAS_RSS_URL = "https://jobregister.aas.org/rss"

    feed = http.get_feed(AAS_RSS_URL,
                         headers={"Referer": "https://jobregister.aas.org/"})
    if feed and getattr(feed, "entries", None):
        return _feed_records(feed, "aas")

    # The old approach guessed a category PATH
    # (jobregister.aas.org/jobs/pre-doctoral-graduate). The live board is a
    # Drupal facet UI on aas.org, where a position category is a numeric ID:
    #     https://aas.org/jobregister?f[0]=category:511&f[1]=category:512
    # so the PhD/postdoc split can happen server-side instead of being guessed
    # from a page title afterwards. The IDs are data — see url_registry.yaml.
    spec = registry.spec_for("aas")
    urls = spec.urls_for(getattr(cfg, "field_profile", None)) if spec else []
    if not urls:
        log.info("[aas] no category facets registered for profile %r — "
                 "skipping (set source_options.aas.category)",
                 getattr(cfg, "field_profile", None))
        return []

    log.info("[aas] RSS blocked — trying a browser on %s", urls[0])
    out, seen = [], set()
    for listing in urls:
        html = http.get_rendered(listing,
                                 wait_selector="a[href*='/jobregister/']",
                                 timeout_ms=30000)
        if not html:
            continue
        soup = BeautifulSoup(html, _HTML_PARSER)
        for a in soup.find_all("a", href=re.compile(r"/jobregister/|/jobs/\d+")):
            href = a.get("href", "")
            url = href if href.startswith("http") else "https://aas.org" + href
            title = a.get_text(" ", strip=True)
            if url in seen or not title:
                continue
            seen.add(url)
            # Position type is NOT forced here any more: the old code stamped
            # "phd" on everything because the URL it used was a PhD-only path.
            # With the category facet carrying both PhD and postdoc, guessing
            # would mislabel half the board — let the classifier decide.
            out.append(make_record(title=title, url=url, source="aas"))
    if not out:
        log.warning("[aas] 0 listings after browser render")
    return out
