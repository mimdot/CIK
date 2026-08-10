"""source_academictransfer — AcademicTransfer (NL) via Playwright API
interception, with a server-rendered SSR fallback (migration Step 5, Batch C)."""

from __future__ import annotations

import re
from urllib.parse import quote

from core.config import Config, ISO2_COUNTRY
from core.deps import _HAVE_PLAYWRIGHT
from core.http import BROWSER_HEADERS, Http
from core.records import make_record

from .base import log, register_source


@register_source("academictransfer")
def source_academictransfer(cfg: Config, http: Http) -> list[dict]:
    """[JS] AcademicTransfer (NL). The public site is a Nuxt SPA; its search
    XHR (api.academictransfer.com/vacancies/) requires a session token, and
    the server-rendered HTML ignores the ?q= parameter. So: render the search
    page with Playwright and intercept the JSON the site fetches for itself.
    Falls back to parsing vacancy links out of the server-rendered page.
    """
    if not _HAVE_PLAYWRIGHT:
        log.warning("[academictransfer] needs Playwright; falling back to "
                    "unfiltered SSR page (relevance engine will trim)")
        return _academictransfer_ssr_fallback(cfg, http)

    captured: list[dict] = []

    def _on_response(resp) -> None:
        if ("api.academictransfer.com/vacancies" in resp.url
                and "is_active=true" in resp.url):
            try:
                d = resp.json()
                if d.get("results"):
                    captured.extend(d["results"])
            except Exception:
                pass

    try:
        from playwright.sync_api import sync_playwright as _sp
        with _sp() as pw:
            browser = http._pw_browser(pw, headless=True)
            try:
                ctx_kw = {"locale": "en-US"}
                if http._pw_channel != "chrome":
                    ctx_kw["user_agent"] = BROWSER_HEADERS["User-Agent"]
                page = browser.new_context(**ctx_kw).new_page()
                page.on("response", _on_response)
                for kw in cfg.search_terms[:2]:
                    http._throttle()
                    url = ("https://www.academictransfer.com/en/jobs/?q="
                           + quote(kw))
                    page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    page.wait_for_timeout(8000)  # let the SPA fire its XHR
            finally:
                browser.close()
    except Exception as exc:
        log.warning("[academictransfer] Playwright error: %s — trying SSR "
                    "fallback", exc)
        return _academictransfer_ssr_fallback(cfg, http)

    out: list[dict] = []
    seen: set = set()
    for item in captured:
        vid = item.get("id") or item.get("absolute_url")
        if vid in seen:
            continue
        seen.add(vid)
        country = ISO2_COUNTRY.get((item.get("country_code") or "").upper())
        out.append(make_record(
            title=item.get("title"),
            institution=item.get("organisation_name"),
            country=country or item.get("city"),
            deadline=item.get("end_date"),
            posted_date=item.get("created_datetime"),
            url=item.get("absolute_url"),
            short_description=item.get("excerpt") or item.get("description"),
            source="academictransfer",
        ))

    if not out:
        log.warning("[academictransfer] 0 results from API interception")
    return out


def _academictransfer_ssr_fallback(cfg: Config, http: Http) -> list[dict]:
    """Parse vacancy links out of the server-rendered listing (latest jobs,
    unfiltered — the relevance engine keeps only astronomy)."""
    soup = http.get_soup("https://www.academictransfer.com/en/jobs/")
    if not soup:
        return []
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/en/jobs/\d+/")):
        href = a["href"]
        url = ("https://www.academictransfer.com" + href
               if href.startswith("/") else href)
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True)
        if not title:
            # derive from slug: /en/jobs/361520/phd-position-in-x/
            m = re.search(r"/en/jobs/\d+/([a-z0-9-]+)", href)
            title = m.group(1).replace("-", " ").capitalize() if m else None
        out.append(make_record(title=title, url=url, country="Netherlands",
                               source="academictransfer"))
    return out
