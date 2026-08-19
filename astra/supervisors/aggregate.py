"""supervisors.aggregate — per-author aggregation + ranking of supervisor
candidates (migration Step 9).

Extracted verbatim from ``astra.py``. Pure functions: collapse the
matched papers from any source into per-author stats (publication frequency +
last-author seniority bonus), apply the country + min-papers gates, and rank.
No network, no I/O — directly unit-testable with fixture docs.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from core.config import (SUPERVISOR_MAX_AUTHORS, SUPERVISOR_MIN_PAPERS,
                         SUPERVISOR_SENIOR_WEIGHT, _CANON_TO_ISO2,
                         _compile_term)
from core.utils import canonical_country, clean_oneline, guess_country


def _author_key(name: str) -> Optional[str]:
    """'Beck, Rainer' / 'Beck, R.' / 'Rainer Beck' -> 'beck, r' (ASCII-folded,
    last name + first initial) so ADS name variants merge."""
    import unicodedata
    if not name:
        return None
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii").strip()
    if not text:
        return None
    if "," in text:
        last, _, first = text.partition(",")
    else:
        parts = text.rsplit(" ", 1)
        if len(parts) == 2:
            first, last = parts
        else:
            first, last = "", parts[0]
    last = re.sub(r"[^a-z\- ]", "", last.strip().lower())
    initial = next((c for c in first.strip().lower() if c.isalpha()), "")
    if not last:
        return None
    return f"{last}, {initial}" if initial else last


def _paper_link(bib: Optional[str], url: Optional[str],
                doi: Optional[str]) -> str:
    """Stable link for a representative paper, across sources: ADS bibcode ->
    ADS abstract page; DOI (full URL or bare) -> doi.org; OpenAlex id -> its
    works page."""
    if bib:
        return f"https://ui.adsabs.harvard.edu/abs/{quote(bib)}/abstract"
    if doi:
        doi = str(doi).strip()
        if doi.startswith(("http://", "https://")):
            return doi              # OpenAlex returns full DOI URLs
        return f"https://doi.org/{quote(doi, safe='/')}"
    return url or ""


def aggregate_supervisors(docs: list[dict], country: Optional[str],
                          keywords: list[str],
                          min_papers: int = SUPERVISOR_MIN_PAPERS,
                          senior_weight: float = SUPERVISOR_SENIOR_WEIGHT,
                          max_authors: int = SUPERVISOR_MAX_AUTHORS,
                          search_fmt: Optional[str] = None,
                          ) -> list[dict]:
    """Aggregate per-author stats over the matched papers and rank supervisor
    candidates. Pure function (self-tested offline).

    Scoring: +1 per matched paper, +senior_weight extra when the author is
    the LAST author (usually the PI). When `country` is given, an author only
    accumulates from papers where THEIR OWN affiliation matches it.

    `search_fmt` is a format string with a {name} placeholder for the
    "search this person's papers" link, source-appropriate (ADS, OpenAlex...).
    Default: NASA ADS author search."""
    if search_fmt is None:
        search_fmt = 'https://ui.adsabs.harvard.edu/search/q=author:"{name}"'
    target = canonical_country(country) if country else None
    target_code = _CANON_TO_ISO2.get(target) if target else None
    kw_rx = [(kw, _compile_term(kw)) for kw in keywords]
    cand: dict[str, dict] = {}

    for doc in docs:
        authors = doc.get("authors") or []
        n = len(authors)
        if not n or n > max_authors:      # mega-collaborations say nothing
            continue                      # about who supervises whom
        affs = doc.get("affs") or []
        orcids = doc.get("orcids") or []
        author_codes = doc.get("author_countries") or []
        for i, name in enumerate(authors):
            aff = (affs[i] if i < len(affs) else "") or ""
            if aff == "-":
                aff = ""
            codes = (author_codes[i] if i < len(author_codes) else []) or []
            if isinstance(codes, str):
                codes = [codes]
            codes = [c.upper() for c in codes if c]
            aff_country = guess_country(aff)
            verified = (aff_country == target) if target else bool(aff_country)
            if target and codes:
                # structured per-author country codes (OpenAlex) beat free-text
                # guessing: only count the author when one of THEIR OWN
                # affiliations is in the target country.
                verified = target_code in codes
            if target and aff and aff_country and not verified:
                continue                  # author is elsewhere — skip
            if target and not aff and not codes:
                continue                  # can't verify -> don't count (ADS);
                                          # arXiv path passes country=None
            key = _author_key(name)
            if not key:
                continue
            slot = cand.setdefault(key, {
                "name": name, "papers": 0, "last_author": 0, "score": 0.0,
                "affs": {}, "orcid": None, "recent": [], "countries": {},
            })
            if len(str(name)) > len(str(slot["name"])):
                slot["name"] = name       # keep the fullest name variant
            is_last = (i == n - 1 and n > 1)
            slot["papers"] += 1
            slot["last_author"] += int(is_last)
            slot["score"] += 1.0 + (senior_weight if is_last else 0.0)
            if aff:
                slot["affs"][aff] = slot["affs"].get(aff, 0) + 1
            if aff_country:
                slot["countries"][aff_country] = \
                    slot["countries"].get(aff_country, 0) + 1
            orcid = (orcids[i] if i < len(orcids) else "") or ""
            if orcid and orcid != "-" and not slot["orcid"]:
                slot["orcid"] = orcid
            try:                          # ADS returns year as a string
                year = int(doc.get("year") or 0)
            except (TypeError, ValueError):
                year = 0
            slot["recent"].append((year,
                                   clean_oneline(doc.get("title")) or "",
                                   doc.get("bibcode"), doc.get("url"),
                                   doc.get("doi")))

    rows: list[dict] = []
    for slot in cand.values():
        if slot["papers"] < min_papers:
            continue
        top_aff = max(slot["affs"], key=slot["affs"].get) if slot["affs"] else None
        top_country = (max(slot["countries"], key=slot["countries"].get)
                       if slot["countries"] else None)
        recent = sorted(slot["recent"], key=lambda t: -(t[0] or 0))[:3]

        papers_fmt = " | ".join(
            f"{title[:90]} ({year}) {_paper_link(bib, url, doi)}".rstrip()
            for year, title, bib, url, doi in recent)
        topics = sorted({kw for kw, rx in kw_rx
                         if any(rx.search(t[1]) for t in slot["recent"])})
        rows.append({
            "name": slot["name"],
            "institution": top_aff,
            "country": (canonical_country(country) if country
                        else top_country or "unverified"),
            "score": round(slot["score"], 1),
            "papers": slot["papers"],
            "last_author_papers": slot["last_author"],
            "topics": "; ".join(topics) or None,
            "representative_papers": papers_fmt or None,
            "author_search": search_fmt.format(name=quote(slot["name"], safe="")),
            "orcid": slot["orcid"],
            "orcid_link": (f"https://orcid.org/{slot['orcid']}"
                           if slot["orcid"] else None),
            "public_email": None,          # filled only from public ORCID
            "email_source": None,
        })
    rows.sort(key=lambda r: (-r["score"], -r["papers"], r["name"]))
    return rows
