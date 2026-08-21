"""supervisors.openalex — OpenAlex queries for --find-supervisors (migration
Step 9). Extracted verbatim from astra.py.

OpenAlex covers EVERY major (no token, polite pool via mailto). Two paths:
keyword-matched WORKS (fallback for old/custom profiles) and the author-direct
search via the profile's curated topics + country, ranked by h-index and
recent activity with balanced country/field verification.
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import date
from typing import Optional

from core.config import (OPENALEX_API, OPENALEX_AUTHORS_API, OPENALEX_MAILTO,
                         SUPERVISOR_COUNTRY_BOOST, SUPERVISOR_MAX_PAPERS,
                         SUPERVISOR_RECENCY_WEIGHT, Config, _CANON_TO_ISO2,
                         _oa_field_id)
from core.utils import _key_text, canonical_country, clean_oneline
from supervisors.aggregate import _paper_link

log = logging.getLogger("astra")


def openalex_supervisor_docs(cfg: Config, http, keywords: list[str],
                             country: str) -> list[dict]:
    """OpenAlex — covers EVERY major (CS, economics, biology, chemistry,
    engineering, geology, math...), no token, structured author affiliations +
    ORCIDs. Papers matching the keywords' title/abstract published in the last
    N years with >=1 author institution in `country` (authorships.countries
    filter), normalized to the shared {title, year, authors, affs, orcids, url}
    schema so aggregate_supervisors() works unchanged."""
    year0 = date.today().year - cfg.supervisor_years_back
    code = _CANON_TO_ISO2.get(canonical_country(country) or "")
    filters = [f"from_publication_date:{year0}-01-01"]
    if code:
        filters.append(f"authorships.countries:{code}")
    else:
        log.warning("[supervisors] OpenAlex: no ISO2 code for country %r — "
                    "searching without a country filter", country)
    mailto = os.environ.get("OPENALEX_MAILTO", "") or OPENALEX_MAILTO
    docs: list[dict] = []
    seen: set[str] = set()
    for kw in keywords[:8]:
        if not kw:
            continue
        # title_and_abstract keeps precision high: a paper only counts when the
        # field term is actually IN its title/abstract (full-text "search"
        # would match incidental mentions).
        fq = ",".join(filters + [f"title_and_abstract.search:{kw}"])
        for page in range(1, 6):
            params = {"search": kw, "filter": fq, "page": page,
                      "per-page": 100, "sort": "publication_date:desc",
                      "select": "id,doi,title,publication_year,authorships",
                      "mailto": mailto}
            resp = http.raw_get(OPENALEX_API, params=params)
            if resp is None or resp.status_code >= 400:
                log.warning("[supervisors] OpenAlex query failed: %s (%s)",
                            kw, resp.status_code if resp is not None
                            else "no response")
                break
            data = resp.json()
            results = data.get("results") or []
            for w in results:
                title = clean_oneline(w.get("title")) or ""
                tkey = _key_text(title)
                if tkey in seen:
                    continue          # same paper matched by another keyword
                seen.add(tkey)
                authors, affs, orcids, countries = [], [], [], []
                for a in (w.get("authorships") or []):
                    author = a.get("author") or {}
                    authors.append(author.get("display_name") or "")
                    raw = a.get("raw_affiliation_strings") or []
                    if raw:
                        affs.append(str(raw[0]).strip())
                    else:
                        insts = a.get("institutions") or []
                        affs.append(insts[0].get("display_name")
                                    if insts else "")
                    orcid = author.get("orcid") or ""
                    if orcid.startswith("https://orcid.org/"):
                        orcid = orcid[len("https://orcid.org/"):]
                    orcids.append(orcid or "")
                    countries.append(a.get("countries") or [])
                docs.append({"bibcode": None, "title": title,
                             "year": w.get("publication_year"),
                             "authors": authors, "affs": affs,
                             "orcids": orcids,
                             "author_countries": countries,
                             "url": w.get("id"), "doi": w.get("doi")})
            meta = data.get("meta") or {}
            log.info("[supervisors] OpenAlex %r -> page %d (%d docs so far, "
                     "%d total)", kw, page, len(docs),
                     meta.get("count") or 0)
            if len(results) < 100 or len(docs) >= SUPERVISOR_MAX_PAPERS:
                break
        if len(docs) >= SUPERVISOR_MAX_PAPERS:
            break
    return docs[:SUPERVISOR_MAX_PAPERS]


def _openalex_author_recent(http, cfg: Config, author_id: str,
                            year0: int, code: str, mailto: str,
                            field_id: Optional[str] = None) -> dict:
    """Recent works by an OpenAlex author (cfg.supervisor_recent_works of
    them), flagged per-author and verified for country + field.

    Returns {"works": [...], "in_country": int, "has_country": int,
    "n_field": int} where each work = {title, year, doi, url, is_last,
    is_corr, inst, in_country, field_match}. `inst` is THIS author's own
    affiliation on that work; `in_country` counts works whose structured
    authorships.countries put THIS author in `code`; `has_country` counts
    their recent works that carried country data at all (so a lack of
    confirmation is told apart from a confirmed elsewhere); `n_field`
    counts recent works whose primary_topic belongs to `field_id`. A
    research-network sideline (CEPR/NBER/Ifo...) or a namesake's hospital
    paper can no longer dominate a small work window."""
    works: list[dict] = []
    in_country = 0
    has_country = 0
    n_field = 0
    params = {"filter": f"author.id:{author_id},"
                        f"from_publication_date:{year0}-01-01",
              "per-page": max(1, cfg.supervisor_recent_works),
              "sort": "publication_date:desc",
              "select": "id,doi,title,publication_year,authorships,primary_topic",
              "mailto": mailto}
    resp = http.raw_get(OPENALEX_API, params=params)
    if resp is None or resp.status_code >= 400:
        log.debug("[supervisors] OpenAlex recent-works failed for %s (%s)",
                  author_id, resp.status_code if resp is not None
                  else "no response")
        return {"works": works, "in_country": in_country,
                "has_country": has_country, "n_field": n_field}
    field = _oa_field_id(field_id)
    for w in (resp.json().get("results") or []):
        au = w.get("authorships") or []
        n = len(au)
        mine = None
        for item in au:
            if (item.get("author") or {}).get("id") == author_id:
                mine = item
                break
        if mine is None:
            continue
        mine_cty = [str(c).upper() for c in (mine.get("countries") or [])]
        if mine_cty:
            has_country += 1
            if code in mine_cty:
                in_country += 1
        insts = mine.get("institutions") or []
        raw = mine.get("raw_affiliation_strings") or []
        inst = (insts[0].get("display_name") if insts
                else str(raw[0]).strip() if raw else "")
        inst = re.sub(r"\s+", " ", inst or "").strip()[:100]
        pos = (mine.get("author_position") or "").lower()
        pt_field = _oa_field_id((w.get("primary_topic") or {}).get("field")
                                or {})
        field_match = bool(field and pt_field == field)
        if field_match:
            n_field += 1
        works.append({
            "title": clean_oneline(w.get("title")) or "",
            "year": w.get("publication_year"),
            "doi": w.get("doi"),
            "url": w.get("id"),
            "is_last": bool(n > 1 and pos == "last"),
            "is_corr": bool(mine.get("is_corresponding")),
            "inst": inst,
            "in_country": bool(code in mine_cty),
            "field_match": field_match,
        })
    return {"works": works, "in_country": in_country,
            "has_country": has_country, "n_field": n_field}


def _openalex_works_pool(cfg: Config, http, topics: list[str],
                         field_id: Optional[str], code: str, mailto: str,
                         year0: int, cancel=None,
                         on_progress=None) -> dict[str, dict]:
    """Country-verified candidate pool for the author-direct supervisor path.

    Queries the WORKS index (not the fragile `last_known_institutions` author
    filter) for recent papers by authors publishing from the target country in
    the profile's topics — or its OpenAlex field when no topics are curated —
    then counts per author how many of THEIR OWN authorships list the target
    country. An author qualifies when they publish from the country often
    enough (>= supervisor_min_papers), which is what keeps foreign mega-stars
    with a single CEPR/NBER/Ifo-style research-network link out of the pool.

    Returns {author_id: {"in_country": n, "matched": n, "latest": year}}."""
    stats: dict[str, dict] = {}
    if topics:
        batches = [[t for t in topics[i:i + 6] if t]
                   for i in range(0, len(topics), 6)]
        batches = [b for b in batches if b]
    elif field_id:
        batches = [[]]                    # field-only profiles use the field
    else:
        return {}
    for bi, batch in enumerate(batches, 1):
        if batch:
            topic_f = f"topics.id:{'|'.join(batch)}"
        else:
            topic_f = f"primary_topic.field.id:{_oa_field_id(field_id)}"
        filters = [f"authorships.countries:{code}",
                   f"from_publication_date:{year0}-01-01", topic_f]
        for page in range(1, max(1, cfg.supervisor_pool_pages) + 1):
            if on_progress:
                try:
                    on_progress({"event": "stage",
                                 "label": f"scanning recent papers "
                                          f"(batch {bi}/{len(batches)}, "
                                          f"page {page}) — "
                                          f"{len(stats)} people so far"})
                except Exception:
                    pass
            # Stop between pages: each is a full OpenAlex round trip, so this
            # bounds a cancelled search to the request already in flight.
            if cancel is not None and cancel.is_cancelled():
                log.info("[supervisors] cancelled while building the pool")
                return {aid: st for aid, st in stats.items()
                        if st["in_country"] >= cfg.supervisor_min_papers}
            params = {"filter": ",".join(filters), "page": page,
                      "per-page": 100, "sort": "publication_date:desc",
                      "select": "id,publication_year,authorships",
                      "mailto": mailto}
            resp = http.raw_get(OPENALEX_API, params=params)
            if resp is None or resp.status_code >= 400:
                status = resp.status_code if resp is not None else "no response"
                log.warning("[supervisors] OpenAlex works-pool query failed "
                            "(%s)", status)
                # SAY WHY. A 429 here is not "there are no supervisors in this
                # country" — it is OpenAlex refusing to talk to this network,
                # and it returns an empty search that looks identical to a
                # genuine no-match. Measured on a throttled exit IP: every
                # request 429, with and without a mailto, so the user has no
                # way to tell a rate limit from an empty field.
                if status == 429 and on_progress:
                    try:
                        on_progress({
                            "event": "stage",
                            "label": "OpenAlex is rate-limiting this network "
                                     "(HTTP 429) — results will be incomplete. "
                                     "Try again later or on another network.",
                            "rate_limited": True})
                    except Exception:
                        pass
                break
            results = (resp.json().get("results") or [])
            for w in results:
                year = w.get("publication_year") or 0
                for a in (w.get("authorships") or []):
                    aid = ((a.get("author") or {}).get("id") or "").rstrip("/")
                    if not aid:
                        continue
                    st = stats.setdefault(
                        aid, {"in_country": 0, "matched": 0, "latest": 0})
                    st["matched"] += 1
                    if year and year > st["latest"]:
                        st["latest"] = year
                    if code in {str(c).upper()
                                for c in (a.get("countries") or [])}:
                        st["in_country"] += 1
            if len(results) < 100:
                break
    kept = {aid: st for aid, st in stats.items()
            if st["in_country"] >= cfg.supervisor_min_papers}
    log.info("[supervisors] OpenAlex works-pool: %d unique authors, %d of them "
             "publish from %s often enough (>= %d of their OWN works)",
             len(stats), len(kept), code, cfg.supervisor_min_papers)
    return kept


def _openalex_author_records(http, ids: list[str], mailto: str
                             ) -> dict[str, dict]:
    """Fetch full author records (h-index, affiliations-with-years, topics,
    ORCID...) for many ids in a few batched calls. OpenAlex caps the
    `openalex_id:` filter at 100 values, so batches use that limit."""
    records: dict[str, dict] = {}
    sel = ("id,display_name,orcid,works_count,cited_by_count,summary_stats,"
           "affiliations,topics,last_known_institutions")
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        params = {"filter": f"openalex_id:{'|'.join(chunk)}",
                  "per-page": 100, "select": sel, "mailto": mailto}
        resp = http.raw_get(OPENALEX_AUTHORS_API, params=params)
        if resp is None or resp.status_code >= 400:
            log.warning("[supervisors] OpenAlex author-records batch failed "
                        "(%s)", resp.status_code if resp is not None
                        else "no response")
            continue
        for a in (resp.json().get("results") or []):
            aid = (a.get("id") or "").rstrip("/")
            if aid:
                records[aid] = a
    return records


def _author_current_institution(record: dict, code: str) -> Optional[str]:
    """Most recent ACTIVE institution in the target country from the author's
    OpenAlex `affiliations` (institution + years), preferring universities
    (type education) over think-tanks / research networks / companies /
    hospitals — so a CEPR/NBER/Ifo sideline is never shown as an employer."""
    best: Optional[tuple[int, bool, str]] = None
    cutoff = date.today().year - 3
    for e in (record.get("affiliations") or []):
        inst = e.get("institution") or {}
        name = inst.get("display_name")
        years = e.get("years") or []
        if not name or not years:
            continue
        try:
            latest = max(int(y) for y in years)
        except (TypeError, ValueError):
            continue
        if latest < cutoff:
            continue
        if (inst.get("country_code") or "").upper() != code:
            continue
        key = (latest, inst.get("type") == "education", str(name))
        if best is None or key > best:
            best = key
    return best[2] if best else None


def openalex_supervisor_authors(cfg: Config, http,
                                topics: list[str], country: str,
                                field_id: Optional[str] = None,
                                cancel=None, on_progress=None
                                ) -> list[dict]:
    """OpenAlex supervisor path for --find-supervisors (any major, no token).

    Candidate pool: recent WORKS by authors publishing from the target country
    in the profile's curated topics (or its OpenAlex field) — the works-level
    `authorships.countries` check guarantees the person really works there
    now, instead of OpenAlex's noisy `last_known_institutions` (which matches
    ANY past affiliation and leaked foreign mega-stars into the economics
    results via CEPR/NBER/Ifo links).

    Ranking: author career stats (h-index) + recent activity. Each candidate
    is verified against their OWN recent works: a majority of the works that
    carry country data must be from the target country, and a minimum share
    must belong to the profile's field — so namesake doctors / biotech /
    unrelated researchers are filtered out. Institution = most recent ACTIVE
    education-type institution in the target country (a research network is
    never shown as an employer).

    Returns rows in the aggregate_supervisors() output schema (score, papers,
    representative_papers, orcid, author_search...) so the rest of the
    pipeline — ORCID email lookup, CSV/JSON/HTML, printing — is unchanged.
    Empty list when nothing matched.

    ``cancel`` and ``on_progress`` are polled and emitted INSIDE this function's
    loops, which is where a supervisor search actually spends its minutes.
    sync_supervisors only checks them between field/country pairs, and the
    desktop searches exactly one pair — so a Stop click did nothing at all and
    the dialog sat at 0/1 for the whole run. Whatever was verified before a
    stop is returned rather than discarded: a cancelled search is a shortened
    one."""
    def _stopped() -> bool:
        return cancel is not None and cancel.is_cancelled()

    def _emit(**payload) -> None:
        if on_progress:
            try:
                on_progress(payload)
            except Exception:      # progress must never break a search
                pass

    code = _CANON_TO_ISO2.get(canonical_country(country) or "")
    if not code:
        log.warning("[supervisors] OpenAlex author search: no ISO2 code for "
                    "country %r — cannot run (use --country Germany etc.)",
                    country)
        return []
    mailto = os.environ.get("OPENALEX_MAILTO", "") or OPENALEX_MAILTO
    year0 = date.today().year - cfg.supervisor_years_back

    _emit(event="stage", label=f"{country}: finding who publishes here")
    pool = _openalex_works_pool(cfg, http, topics, field_id, code, mailto,
                                year0, cancel=cancel, on_progress=on_progress)
    if not pool:
        log.warning("[supervisors] OpenAlex author search: no authors publish "
                    "from %s in the profile's topics", country)
        return []
    if _stopped():
        return []

    _emit(event="stage",
          label=f"{country}: fetching {len(pool)} candidate profiles")
    records = _openalex_author_records(http, list(pool), mailto)
    if not records:
        log.warning("[supervisors] OpenAlex author search: could not fetch "
                    "author records for the %d-pool candidates", len(pool))
        return []

    def _h(rec: dict) -> int:
        return (rec.get("summary_stats") or {}).get("h_index") or 0

    def _aid(rec: dict) -> str:
        return (rec.get("id") or "").rstrip("/")

    ordered = sorted(
        (rec for rec in records.values() if _aid(rec) in pool),
        key=lambda rec: (-_h(rec), -(pool[_aid(rec)]["in_country"]),
                         -(rec.get("cited_by_count") or 0)))
    wanted = {t if t.startswith("http") else f"https://openalex.org/{t}"
              for t in topics}
    signal = (cfg.supervisor_senior_signal or "last_author").lower()
    need_field = bool(_oa_field_id(field_id))
    in_share = cfg.supervisor_min_in_country_share
    field_share = cfg.supervisor_min_field_share

    rows: list[dict] = []
    accepted = 0
    attempted = 0
    max_attempts = cfg.supervisor_author_enrich * 3
    # The loop below is where a supervisor search spends nearly all of its
    # time: one HTTP round trip per candidate, up to author_enrich*3 of them.
    # Cancel is polled every iteration and progress is emitted every iteration,
    # so Stop takes effect within one request and the dialog visibly counts.
    target = min(cfg.supervisor_author_enrich, len(ordered))
    _emit(event="stage", label=f"{country}: checking candidates", total=target)
    for rec in ordered:
        if accepted >= cfg.supervisor_author_enrich or attempted >= max_attempts:
            break
        if _stopped():
            log.info("[supervisors] cancelled after %d candidates — keeping "
                     "the %d already verified", attempted, len(rows))
            break
        attempted += 1
        # Emitted BEFORE the request, every single candidate. Acceptance is
        # rare — most candidates are rejected on country or field — so a
        # counter that only moves on a hit can sit still for a long time and
        # is indistinguishable from a frozen search. This one always moves.
        _emit(event="stage",
              label=f"{country}: checking candidate {attempted}"
                    f" — {accepted} found so far")
        aid = _aid(rec)
        info = _openalex_author_recent(http, cfg, aid, year0, code, mailto,
                                       field_id)
        recent = info["works"]
        n = len(recent)
        if not n:
            continue                        # no recent works -> not active
        in_c = info["in_country"]
        has_c = info["has_country"]
        # Country (balanced majority rule over works that carried country data;
        # a single research-network paper must not misplace a foreign star).
        need = max(cfg.supervisor_min_papers,
                   math.ceil(has_c * in_share)) if has_c >= 3 \
            else cfg.supervisor_min_papers + (0 if has_c else 1)
        if in_c < need:
            continue
        # Field: min share of recent works inside the profile's OpenAlex field;
        # fall back to the profile's core anchors when no field id is known.
        if need_field:
            if info["n_field"] < n * field_share:
                ok_field = any(
                    any(rx.search(w["title"]) for _, rx in cfg._core_rx)
                    for w in recent)
            else:
                ok_field = True
        else:
            ok_field = any(
                any(rx.search(w["title"]) for _, rx in cfg._core_rx)
                for w in recent)
        if not ok_field:
            continue
        h = _h(rec)
        score = float(h) + SUPERVISOR_RECENCY_WEIGHT * min(n, 10)
        if in_c:
            score += SUPERVISOR_COUNTRY_BOOST
        # "where do they work NOW": most recent active education institution in
        # the target country, then any active in-country affiliation, then the
        # first in-country affiliation on their recent works, then last_known.
        inst_name = _author_current_institution(rec, code)
        if inst_name is None:
            inst_name = next((w["inst"] for w in recent
                              if w.get("in_country") and w.get("inst")), None)
        if inst_name is None:
            for inst in (rec.get("last_known_institutions") or []):
                if (inst.get("country_code") or "").upper() == code and \
                        inst.get("display_name"):
                    inst_name = inst["display_name"]
                    break
        if inst_name is None:
            insts = rec.get("last_known_institutions") or []
            inst_name = (insts[0].get("display_name") if insts else None)
        matched = [t.get("display_name") for t in (rec.get("topics") or [])
                   if (t.get("id") or "").rstrip("/") in wanted]
        if signal == "last_author":
            senior_papers = sum(1 for w in recent if w["is_last"])
        elif signal == "corresponding":
            senior_papers = sum(1 for w in recent if w["is_corr"])
        else:
            senior_papers = 0
        recent = sorted(recent, key=lambda w: -(w["year"] or 0))
        papers_fmt = " | ".join(
            f"{w['title'][:90]} ({w['year']}) "
            f"{_paper_link(None, w['url'], w['doi'])}".rstrip() for w in recent)
        orcid = (rec.get("orcid") or "").strip()
        rows.append({
            "name": rec.get("display_name") or "",
            "institution": inst_name,
            "country": canonical_country(country),
            "score": round(score, 1),
            "papers": n,
            "last_author_papers": senior_papers,
            "topics": "; ".join(matched) or None,
            "representative_papers": papers_fmt or None,
            "author_search": aid,          # direct link to their profile page
            "orcid": orcid.rsplit("/", 1)[-1] or None,
            "orcid_link": orcid or None,
            "public_email": None,
            "email_source": None,
        })
        accepted += 1
        # A found supervisor, named, as soon as they are verified — the dialog
        # can list results while the search is still running instead of showing
        # nothing until the very end.
        _emit(event="candidate", completed=accepted, total=target,
              attempted=attempted,
              name=rows[-1]["name"], institution=rows[-1]["institution"],
              score=int(rows[-1].get("score") or 0))
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    log.info("[supervisors] OpenAlex author-direct: %d ranked candidates "
             "(%d in the country+field pool, h-index + recency scoring)",
             len(rows), len(ordered))
    return rows
