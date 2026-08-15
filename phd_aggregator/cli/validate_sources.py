"""cli.validate_sources — request every registered source URL and report.

The failure this exists to catch: a board answers 200 with an empty result set
(or its own 404 page), the crawler parses zero listings, and the run reports
"0 found" as though the discipline had no openings. Status code alone cannot
tell those apart — so this counts PARSED LISTINGS, not bytes, and flags any
target that returns none.

Re-runnable by design: sites drift, slugs get renamed, facet IDs get renumbered.
Run it whenever a field mysteriously goes quiet.

    python3 phd_aggregator.py --validate-sources
    python3 phd_aggregator.py --validate-sources --field astronomy
    python3 phd_aggregator.py --validate-sources --source euraxess --json
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Optional

from core.deps import _HTML_PARSER
from sources.registry import ANY_FIELD, iter_entries, load_registry

log = logging.getLogger("phd_aggregator")


@dataclass
class ValidationResult:
    source: str
    field: str
    url: str
    status: Optional[int]
    listings: int
    ok: bool
    detail: str
    declared: str          # what the registry CLAIMED before this run
    elapsed_ms: int = 0


def _count_listings(html: str, selector: str) -> int:
    """Parsed listings on the page — the only number that means anything."""
    if not html:
        return 0
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, _HTML_PARSER)
    except Exception:
        return 0
    if not selector:
        return 0
    try:
        return len(soup.select(selector))
    except Exception as exc:
        log.debug("bad selector %r: %s", selector, exc)
        return 0


def _fingerprint(html: str) -> str:
    """Stable-ish hash of a page's visible text, for spotting identical pages."""
    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, _HTML_PARSER).get_text(" ", strip=True)
    except Exception:
        text = html
    return hashlib.md5(text.encode("utf-8", "replace")).hexdigest()[:12]


def _fallback_fingerprint(http, spec) -> Optional[str]:
    """What this board serves for a slug that does NOT exist.

    Some boards answer 200 with a generic listing for any unknown path, so a
    wrong slug looks exactly like a working one: real HTTP status, real
    listings, entirely the wrong result set. That is how five AcademicJobsOnline
    categories (mathematics, statistics, economics, engineering, geosciences)
    passed as healthy for months while serving the same fallback page.

    Requesting a deliberately nonsense slug once per source gives us the
    signature to compare every real target against.
    """
    if "{" not in spec.url_template or spec.transport == "browser":
        return None
    key = spec.param or "value"
    try:
        url = spec.url_template.format(**{key: "zzz-not-a-real-category-xyz"})
    except Exception:
        return None
    status, html, _ = _fetch(http, url, spec)
    if not status or not (200 <= status < 300) or not html:
        return None            # a proper 404 — this board does not do fallbacks
    return _fingerprint(html)


def _fetch(http, url: str, spec, timeout_ms: int = 30000):
    """Return (status, html, detail) for one target, honouring its transport."""
    if spec.transport == "browser":
        # Cloudflare-guarded boards: the browser chain is the only client they
        # answer. domcontentloaded + wait_for_selector, never networkidle.
        try:
            html = http.get_rendered(
                url, wait_selector=spec.result_selector or None,
                timeout_ms=timeout_ms)
        except Exception as exc:
            return None, "", f"{type(exc).__name__}: {exc}"
        if not html:
            return None, "", "browser returned nothing (blocked or no browser)"
        return 200, html, "rendered"
    try:
        resp = http.get(url)
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {exc}"
    if resp is None:
        return None, "", "no response (blocked, proxy down, or robots-denied)"
    status = getattr(resp, "status_code", None)
    return status, getattr(resp, "text", "") or "", ""


def validate_sources(cfg, http, only_source: Optional[str] = None,
                     only_field: Optional[str] = None,
                     as_json: bool = False) -> int:
    """Check every registered (source, field) URL. Returns a process exit code
    (0 = every target returned listings, 1 = at least one returned none)."""
    registry = load_registry()
    if not registry:
        print("No URL registry found (sources/url_registry.yaml). Nothing to "
              "validate.")
        return 1

    keywords = list(getattr(cfg, "search_terms", None) or [])[:1] or ["phd"]
    results: list[ValidationResult] = []
    fallbacks: dict[str, Optional[str]] = {}

    for spec, target in iter_entries():
        if only_source and spec.name != only_source:
            continue
        if only_field and target.field not in (only_field, ANY_FIELD):
            continue
        if spec.name not in fallbacks:
            fallbacks[spec.name] = _fallback_fingerprint(http, spec)
        for url in spec.urls_for(target.field, keywords=keywords):
            started = time.time()
            status, html, detail = _fetch(http, url, spec)
            listings = _count_listings(html, spec.result_selector)
            ok = bool(status and 200 <= status < 300 and listings > 0)
            # A page identical to the board's unknown-slug page is the WRONG
            # result set, however many listings it happens to contain.
            fb = fallbacks.get(spec.name)
            if ok and fb and _fingerprint(html) == fb:
                ok = False
                detail = ("serves the board's generic fallback page — this "
                          "slug does not exist")
            if not detail:
                if status is None:
                    detail = "unreachable"
                elif not (200 <= status < 300):
                    detail = f"HTTP {status}"
                elif listings == 0:
                    detail = "0 listings parsed (wrong URL or stale selector)"
                else:
                    detail = "ok"
            results.append(ValidationResult(
                source=spec.name, field=target.field, url=url, status=status,
                listings=listings, ok=ok, detail=detail,
                declared=target.status,
                elapsed_ms=int((time.time() - started) * 1000)))

    if as_json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        _print_table(results)
    return 0 if results and all(r.ok for r in results) else 1


def _print_table(results: list[ValidationResult]) -> None:
    if not results:
        print("No registry entries matched.")
        return
    w_src = max(6, max(len(r.source) for r in results))
    w_fld = max(5, max(len(r.field) for r in results))
    header = (f"{'SOURCE':<{w_src}}  {'FIELD':<{w_fld}}  {'HTTP':>5}  "
              f"{'LISTINGS':>8}  {'WAS':<10}  DETAIL")
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda r: (not r.ok, r.source, r.field)):
        mark = "ok " if r.ok else "FAIL"
        status = str(r.status) if r.status is not None else "-"
        print(f"{r.source:<{w_src}}  {r.field:<{w_fld}}  {status:>5}  "
              f"{r.listings:>8}  {r.declared:<10}  {mark} {r.detail}")
        if not r.ok:
            print(f"{'':<{w_src}}  {'':<{w_fld}}  {'':>5}  {'':>8}  "
                  f"{'':<10}      {r.url}")

    total = len(results)
    good = sum(1 for r in results if r.ok)
    print()
    print(f"{good}/{total} target(s) returned listings.")
    zero = [r for r in results if not r.ok]
    if zero:
        print(f"{len(zero)} returned nothing — those fields will silently come "
              f"back empty in a real run.")
        print("Fix the entry in sources/url_registry.yaml (or override it in "
              "the field profile's source_options) and re-run.")
