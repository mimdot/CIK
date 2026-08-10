"""supervisors.arxiv — arXiv API fallback for --find-supervisors (migration
Step 9). Extracted verbatim from phd_aggregator.py.

No token needed; affiliations are only present when authors supplied them, so
country verification is best-effort (callers pass country=None and normalize
afterwards).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date

from core.config import Config
from core.deps import _HAVE_FEEDPARSER, feedparser

log = logging.getLogger("phd_aggregator")

ARXIV_API = "http://export.arxiv.org/api/query"


def arxiv_supervisor_docs(cfg: Config, http,
                          keywords: list[str]) -> list[dict]:
    """arXiv fallback (no token). Affiliations are only present when authors
    supplied them — country verification is best-effort."""
    if not _HAVE_FEEDPARSER:
        log.warning("[supervisors] feedparser missing — cannot use the arXiv "
                    "fallback (pip install feedparser)")
        return []
    docs: list[dict] = []
    cats = [c.strip() for c in cfg.supervisor_arxiv_cat.split(",")
            if c.strip()] if cfg.supervisor_arxiv_cat and \
        cfg.supervisor_arxiv_cat != "all" else []
    cat_clause = (f"(cat:{' OR cat:'.join(cats)}) AND " if cats else "")
    for kw in keywords[:5]:
        params = {"search_query": f'{cat_clause}all:"{kw}"',
                  "start": 0, "max_results": 75,
                  "sortBy": "submittedDate", "sortOrder": "descending"}
        resp = http.raw_get(ARXIV_API, params=params)
        time.sleep(1.5)                     # arXiv asks for gentle pacing
        if resp is None or resp.status_code >= 400:
            log.warning("[supervisors] arXiv query failed: %s", kw)
            continue
        feed = feedparser.parse(resp.content)
        for e in getattr(feed, "entries", []):
            authors, affs = [], []
            for au in getattr(e, "authors", []):
                authors.append((au.get("name") or "").strip())
                affs.append((au.get("arxiv_affiliation") or "").strip())
            year = None
            m = re.match(r"(\d{4})", e.get("published") or "")
            if m:
                year = int(m.group(1))
            docs.append({"bibcode": None, "title": e.get("title") or "",
                         "year": year, "authors": authors, "affs": affs,
                         "orcids": [], "url": e.get("link")})
        log.info("[supervisors] arXiv %r -> %d entries", kw,
                 len(getattr(feed, "entries", [])))
    return docs
