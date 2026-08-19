#!/usr/bin/env python3
"""Sweep the supervisor finder across every field profile (+ each subfield)
and report whether each target yields ranked PhD-supervisor candidates.

Reuses the real pipeline (ADS token from .env when present, the OpenAlex
author-direct path via the profile's curated topics, keyword-works and arXiv
fallbacks). Does NOT do ORCID lookups or write output files.

Usage:
    python test_supervisors.py                 # whole profile + every subfield
    python test_supervisors.py --whole-only     # whole profile per major
    SUPERVISOR_TEST_COUNTRY=Japan python test_supervisors.py

Exit code 0 iff every target produced at least one candidate."""
import argparse
import os
import sys
import time
from argparse import Namespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import astra as P

COUNTRY = os.environ.get("SUPERVISOR_TEST_COUNTRY", "Germany")
MIN_CANDS = int(os.environ.get("SUPERVISOR_TEST_MIN", "5"))


def one_target(profile: str, sub: str | None, token: str) -> dict:
    cfg = P.build_config(Namespace(no_config=True, debug=False,
                                   phd_only=False, field=None))
    prof = P.load_field_profile(profile) or {}
    P.apply_field_profile(cfg, prof)
    cfg.field_profile = profile
    cfg.subfield = sub
    P.compile_taxonomy(cfg)
    cfg.countries = [COUNTRY]
    cfg.delay = 0.4
    # keep the sweep fast: small pool + few enrichments per target
    cfg.supervisor_pool_pages = 1
    cfg.supervisor_author_enrich = 5
    cfg.supervisor_recent_works = 10
    label, keywords, topics = P._supervisor_focus(cfg)

    http = P.Http(cfg)
    t0 = time.time()
    try:
        ranked, src = [], None
        n_papers = 0
        for s in P._supervisor_chain(cfg, token):
            if s == "ads" and token:
                docs = P.ads_supervisor_docs(cfg, http, token, keywords,
                                             COUNTRY)
                n_papers = len(docs)
                ranked = (P.aggregate_supervisors(docs, COUNTRY, keywords)
                          if docs else [])
                if ranked:
                    src = "ADS"
                    break
            elif s == "openalex":
                if topics:
                    ranked = P.openalex_supervisor_authors(
                        cfg, http, topics, COUNTRY, cfg.supervisor_field)
                    if ranked:
                        src = "OpenAlex"
                        break
                docs = P.openalex_supervisor_docs(cfg, http, keywords, COUNTRY)
                n_papers = len(docs)
                ranked = (P.aggregate_supervisors(docs, COUNTRY, keywords)
                          if docs else [])
                if ranked:
                    src = "OpenAlex"
                    break
            else:  # arxiv
                docs = P.arxiv_supervisor_docs(cfg, http, keywords)
                n_papers = len(docs)
                ranked = (P.aggregate_supervisors(docs, None, keywords)
                          if docs else [])
                target = P.canonical_country(COUNTRY)
                ranked = [r for r in ranked
                          if r["country"] in (target, "unverified")]
                if ranked:
                    src = "arXiv"
                    break
        raw = len(ranked)
        n = len(ranked)
        # A good target: at least MIN candidates AND the top candidate really
        # is in the requested country (both broken before this fix).
        target_cty = P.canonical_country(COUNTRY)
        ok = bool(ranked) and n >= MIN_CANDS and \
            (ranked[0]["country"] == target_cty)
        return {"profile": profile, "field": label, "ok": ok,
                "src": src or "NONE", "n": n, "raw": raw,
                "papers": n_papers,
                "top": (ranked[0]["name"] if ranked else "-"),
                "top_cty": (ranked[0]["country"] if ranked else "-"),
                "sec": round(time.time() - t0, 1)}
    except Exception as exc:
        return {"profile": profile, "field": label, "ok": False,
                "src": f"ERR {type(exc).__name__}", "n": 0, "raw": 0,
                "papers": 0, "top": "-", "top_cty": "-",
                "sec": round(time.time() - t0, 1)}
    finally:
        http.close()


def main() -> int:
    P._load_dotenv()
    token = os.environ.get(P.ADS_TOKEN_ENV)
    print(f"country={COUNTRY}  ADS token={'present' if token else 'MISSING (OpenAlex/arXiv)'}\n")

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--whole-only", action="store_true")
    opts, _ = ap.parse_known_args()

    rows: list[dict] = []
    for profile in P.list_field_profiles():
        prof = P.load_field_profile(profile) or {}
        subs = list((prof.get("subfields") or {}).keys())
        targets = [(profile, None, "whole")] if opts.whole_only else \
            [(profile, None, "whole")] + [(profile, s, "sub") for s in subs]
        for p, s, kind in targets:
            r = one_target(p, s, token)
            rows.append(r)
            print(f"{'OK  ' if r['ok'] else 'FAIL'} "
                  f"{p:<17} [{kind:<5}] {r['field']:<26} "
                  f"src={r['src']:<5} cands={r['n']:<3}(raw {r['raw']:<3}) "
                  f"papers={r['papers']:<4} "
                  f"{r['top'][:28]:<28} {r['top_cty']:<11} {r['sec']}s")

    ok = sum(1 for r in rows if r["ok"])
    with_cand = sorted({r["profile"] for r in rows if r["ok"]})
    without = sorted({r["profile"] for r in rows if not r["ok"]})
    print(f"\nSUMMARY: {ok}/{len(rows)} targets found candidates "
          f"({sum(1 for r in rows if r['ok'] and r['src'] == 'ADS')} via ADS, "
          f"{sum(1 for r in rows if r['ok'] and r['src'] == 'OpenAlex')} via "
          f"OpenAlex, "
          f"{sum(1 for r in rows if r['ok'] and r['src'] == 'arXiv')} via arXiv)")
    print(f"profiles WITH candidates:  {with_cand}")
    print(f"profiles with NO candidate: {without}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
