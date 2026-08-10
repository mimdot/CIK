"""pipeline.parse_page — position-page parsing + per-domain seed adapters
(migration Step 6). Extracted verbatim from the original monolith.

Parses one position page into a normalized record: schema.org JSON-LD
"JobPosting" first, then OpenGraph/<meta> tags, then readability-style main
text. Also hosts the SEED_ADAPTERS registry that the sibling finder
(``sources/seed_urls.py``) consults, and ``extract_page_date`` used by the
freshness stage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core.deps import _HAVE_READABILITY, _HTML_PARSER, _ReadabilityDocument
from core.records import make_record
from core.utils import clean_oneline, normalize_url, parse_date

log = logging.getLogger("phd_aggregator")


def _iter_jsonld_objects(soup) -> Iterable[dict]:
    """Yield every dict found in <script type="application/ld+json"> blocks,
    flattening top-level lists and @graph containers (defensive)."""
    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                if isinstance(node.get("@graph"), list):
                    stack.extend(node["@graph"])


def _jsonld_first(value):
    """JSON-LD values may be scalars, dicts or lists — return one scalar-ish."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value


def _jsonld_name(value) -> Optional[str]:
    value = _jsonld_first(value)
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id")
    return str(value) if value else None


def _jsonld_location(node: dict) -> Optional[str]:
    """Flatten jobLocation (Place/PostalAddress, possibly a list) to text."""
    locs = node.get("jobLocation")
    locs = locs if isinstance(locs, list) else [locs]
    parts: list[str] = []
    for loc in locs:
        if isinstance(loc, str):
            parts.append(loc)
            continue
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address", loc)
        if isinstance(addr, str):
            parts.append(addr)
            continue
        if isinstance(addr, dict):
            for key in ("addressLocality", "addressRegion", "addressCountry"):
                val = addr.get(key)
                if isinstance(val, dict):
                    val = val.get("name")
                if val:
                    parts.append(str(val))
    return ", ".join(dict.fromkeys(p for p in parts if p)) or None


def _meta_content(soup, **attrs) -> Optional[str]:
    el = soup.find("meta", attrs=attrs)
    return el.get("content") if el and el.get("content") else None


def extract_main_text(html: str) -> Optional[str]:
    """Main article text: readability-lxml when installed, else a naive
    boilerplate-stripping fallback on <main>/<article>/<body>."""
    if _HAVE_READABILITY:
        try:
            summary = _ReadabilityDocument(html).summary()
            text = BeautifulSoup(summary, _HTML_PARSER).get_text(" ", strip=True)
            if text and len(text) > 80:
                return text
        except Exception as exc:
            log.debug("readability failed: %s", exc)
    try:
        soup = BeautifulSoup(html, _HTML_PARSER)   # fresh parse — gets mutated
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "form", "noscript"]):
            tag.decompose()
        node = soup.find("main") or soup.find("article") or soup.body or soup
        return node.get_text(" ", strip=True) or None
    except Exception:
        return None


# "Application deadline: 15 August 2026" and friends, in running page text.
_TEXT_DEADLINE_RE = re.compile(
    r"(?:application\s+deadline|closing\s+date|apply\s+by|deadline|"
    r"applications?\s+(?:close|due))\s*[:\-]?\s*([A-Za-z0-9,./\- ]{6,30})", re.I)

def parse_position_page(html: Optional[str], url: str,
                        source: str = "seed_urls") -> Optional[dict]:
    """One position page -> normalized record. JSON-LD JobPosting first, then
    OpenGraph/meta tags, then readability main text. Returns None only when
    not even a title can be recovered."""
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, _HTML_PARSER)
    except Exception as exc:
        log.warning("[%s] HTML parse failed for %s: %s", source, url, exc)
        return None

    title = institution = raw_loc = deadline = posted = desc = None
    parsed_from = None

    # (1) schema.org JSON-LD JobPosting
    for node in _iter_jsonld_objects(soup):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if not any(str(t).lower() == "jobposting" for t in types if t):
            continue
        title = _jsonld_name(node.get("title")) or _jsonld_name(node.get("name"))
        institution = _jsonld_name(node.get("hiringOrganization"))
        raw_loc = _jsonld_location(node)
        posted = node.get("datePosted")
        deadline = node.get("validThrough")
        desc = node.get("description")
        parsed_from = "jsonld"
        break

    # (2) OpenGraph / <meta> tags fill whatever is still missing
    if not title:
        title = (_meta_content(soup, property="og:title")
                 or (soup.title.get_text(strip=True) if soup.title else None))
        parsed_from = parsed_from or "meta"
    if not desc:
        desc = (_meta_content(soup, property="og:description")
                or _meta_content(soup, name="description"))
    if not institution:
        institution = _meta_content(soup, property="og:site_name")
    if not posted:
        posted = _meta_content(soup, property="article:published_time")

    # (3) readability-style main text as the last-resort description
    body_text = None
    if not desc or len(clean_oneline(desc) or "") < 60:
        body_text = extract_main_text(html)
        if body_text:
            desc = body_text
            parsed_from = parsed_from or "text"
    if not deadline:
        text_for_deadline = body_text or extract_main_text(html) or ""
        m = _TEXT_DEADLINE_RE.search(text_for_deadline[:20000])
        if m:
            deadline = m.group(1)

    if not title:
        log.warning("[%s] could not extract even a title from %s — skipped",
                    source, url)
        return None

    rec = make_record(title=title, institution=institution, url=url,
                      deadline=deadline, posted_date=posted,
                      short_description=desc, raw_location=raw_loc,
                      source=source)
    rec["_parsed_from"] = parsed_from       # internal (self-test/debug)
    return rec

# --- per-domain seed adapters -------------------------------------------------
# An adapter tells the sibling finder where a board's LISTING page is and what
# its posting links look like — for boards whose URLs are too irregular for
# the generic path heuristic. Register with the decorator (keyed by bare
# domain, no www.); return {"listings": [urls], "link_re": compiled-regex-on-
# path or None}. See CONTRIBUTING.md for a walk-through.
SEED_ADAPTERS: dict[str, Callable[[str], dict]] = {}


def seed_adapter(domain: str):
    def deco(fn: Callable[[str], dict]):
        d = domain.lower()
        SEED_ADAPTERS[d[4:] if d.startswith("www.") else d] = fn
        return fn
    return deco


def _seed_sibling_pattern(seed_url: str) -> Optional[re.Pattern]:
    """Turn the seed's path into a sibling-matching regex by wildcarding the
    ID/slug segments: /jobs/12345/phd-in-x -> ^/jobs/\\d+/[^/]+/?$ .
    Returns None when no segment looks like an ID/slug (nothing to vary)."""
    try:
        segs = [s for s in urlparse(seed_url).path.split("/") if s]
    except Exception:
        return None
    out, wildcards = [], 0
    for seg in segs:
        if re.fullmatch(r"\d{3,}", seg):
            out.append(r"\d{3,}")
            wildcards += 1
        elif len(seg) >= 10 and seg.count("-") >= 1:
            out.append(r"[^/]+")
            wildcards += 1
        else:
            out.append(re.escape(seg))
    if not wildcards or not out:
        return None
    return re.compile("^/" + "/".join(out) + "/?$", re.I)


_BACK_TO_RESULTS_RE = re.compile(
    r"back to (results|search|list)|all (jobs|vacanc|positions|offers)|"
    r"more (jobs|vacanc|positions)|similar (jobs|positions)|job search", re.I)


def _parent_listing_candidates(seed_url: str, soup) -> list[str]:
    """Guess the board's listing/index page for a seed posting: 'back to
    results'-style links on the page first, then successive path reductions
    of the seed URL itself."""
    cands: list[str] = []
    if soup is not None:
        for a in soup.find_all("a", href=True):
            if _BACK_TO_RESULTS_RE.search(a.get_text(" ", strip=True) or ""):
                cands.append(urljoin(seed_url, a["href"]))
    try:
        p = urlparse(seed_url)
        segs = [s for s in p.path.split("/") if s]
        for i in range(len(segs) - 1, 0, -1):
            cands.append(f"{p.scheme}://{p.netloc}/" + "/".join(segs[:i]) + "/")
    except Exception:
        pass
    seen, out = set(), []
    for u in cands:
        k = normalize_url(u)
        if k and k != normalize_url(seed_url) and k not in seen:
            seen.add(k)
            out.append(u)
    return out[:3]

# "Posted on 12 June 2026" / "Published: 2026-06-12" / "Date posted 12.06.2026"
_POSTED_LINE_RE = re.compile(
    r"(?:posted(?:\s+on)?|published|date\s+posted|advert(?:ised)?\s+date)"
    r"\s*[:\-]?\s*([A-Za-z0-9,./\- ]{6,30})", re.I)


def extract_page_date(html: str) -> Optional[str]:
    """Best-effort posted/updated date from a page: JSON-LD, meta tags, or a
    visible 'Posted on ...' line. Returns ISO date or None."""
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, _HTML_PARSER)
    except Exception:
        return None
    # 1) JSON-LD datePosted / dateModified / datePublished
    for node in _iter_jsonld_objects(soup):
        for key in ("datePosted", "datePublished", "dateModified"):
            d = parse_date(node.get(key))
            if d:
                return d
    # 2) meta tags
    for sel in (("meta", {"property": "article:published_time"}),
                ("meta", {"property": "article:modified_time"}),
                ("meta", {"property": "og:updated_time"}),
                ("meta", {"name": "date"}),
                ("meta", {"itemprop": "datePosted"})):
        el = soup.find(*sel)
        if el and el.get("content"):
            d = parse_date(el["content"])
            if d:
                return d
    # 3) visible "Posted on ..." line
    text = soup.get_text(" ", strip=True)[:20000]
    m = _POSTED_LINE_RE.search(text)
    if m:
        return parse_date(m.group(1))
    return None
