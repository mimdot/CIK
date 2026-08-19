"""supervisors.ads — NASA ADS literature queries for --find-supervisors
(migration Step 9). Extracted verbatim from astra.py.

ADS needs a personal token (env ADS_API_TOKEN / .env); it indexes astronomy
+ physics best, so the source chain prefers it for those majors.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from core.config import (ADS_API_URL, SUPERVISOR_MAX_PAPERS, Config)

log = logging.getLogger("astra")


def _ads_request(http, token: str, params: dict) -> Optional[dict]:
    resp = http.raw_get(ADS_API_URL, params=params,
                        headers={"Authorization": f"Bearer {token}"})
    if resp is None:
        return None
    if resp.status_code == 401:
        log.error("[supervisors] ADS rejected the token (401) — check "
                  "ADS_API_TOKEN (see README: 'Getting an ADS token')")
        return None
    if resp.status_code == 429:
        log.error("[supervisors] ADS rate limit reached (resets daily)")
        return None
    if resp.status_code >= 400:
        log.warning("[supervisors] ADS query failed: HTTP %s %s",
                    resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except Exception as exc:
        log.warning("[supervisors] bad ADS response: %s", exc)
        return None


def ads_supervisor_docs(cfg: Config, http, token: str,
                        keywords: list[str], country: str) -> list[dict]:
    """Recent refereed papers matching the keywords with >=1 affiliation in
    the target country, normalized to {title, year, authors, affs, orcids,
    bibcode} dicts."""
    year0 = date.today().year - cfg.supervisor_years_back
    kw_clause = " OR ".join(f'abs:"{kw}"' for kw in keywords[:8])
    query = (f'({kw_clause}) AND aff:"{country}" '
             f'AND pubdate:[{year0}-01 TO *] AND property:refereed')
    docs: list[dict] = []
    rows = 200
    fq = ([f"database:{cfg.supervisor_ads_db}"]
          if cfg.supervisor_ads_db != "all" else [])
    for start in range(0, SUPERVISOR_MAX_PAPERS, rows):
        data = _ads_request(http, token, {
            "q": query, "fq": fq,
            "fl": "bibcode,title,author,aff,year,orcid_pub",
            "rows": min(rows, SUPERVISOR_MAX_PAPERS - start),
            "start": start, "sort": "date desc",
        })
        if not data:
            break
        got = (data.get("response") or {}).get("docs") or []
        for d in got:
            docs.append({
                "bibcode": d.get("bibcode"),
                "title": (d.get("title") or [""])[0],
                "year": d.get("year"),
                "authors": d.get("author") or [],
                "affs": d.get("aff") or [],
                "orcids": d.get("orcid_pub") or [],
            })
        total = ((data.get("response") or {}).get("numFound") or 0)
        log.info("[supervisors] ADS: %d/%s docs fetched", len(docs), total)
        if start + rows >= total or not got:
            break
    return docs
