"""selftest — the offline pipeline self-test (migration Step 11).

Extracted verbatim from phd_aggregator.py so the monolith can shrink to a CLI
entry point. Two-pass offline test over the filter/relevance/dedupe/sort/
freshness/new-detection/output pipeline plus the supervisors + toolkit layers;
never touches the network.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

from core.config import (CORE_ANCHORS, CONTEXT_TERMS, MAX_AGE_DAYS,
                         NEGATIVE_TERMS, RELEVANCE_THRESHOLD, RELEVANCE_WEIGHTS,
                         _CANON_TO_ISO2, _HAVE_YAML, _load_yaml_file,
                         _oa_field_id, apply_field_profile, build_config,
                         load_field_profile, resolve_field_arg)
from core.records import OUTPUT_FIELDS, make_record
from core.taxonomy import compile_taxonomy, is_relevant, score_relevance
from core.utils import canonical_country, normalize_url
from pipeline.dedupe import dedupe_records
from pipeline.filter import filter_records
from pipeline.freshness import apply_freshness
from pipeline.parse_page import parse_position_page
from pipeline.run import run
from sources import UNIVERSITY_DEPARTMENTS
from supervisors import (AUTHOR_SEARCH_FMT, _supervisor_chain, _supervisor_focus,
                         aggregate_supervisors, openalex_supervisor_authors)
from toolkit import (APPLICANT_PROFILE, PROFESSOR_SEED, SCHOLARSHIPS,
                     build_email)


def _sample_records() -> list[dict]:
    tomorrow = (date.today() + timedelta(days=30)).isoformat()
    tomorrow2 = (date.today() + timedelta(days=45)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    return [
        # 1 — genuine ISM/radio astronomy PhD (must be ACCEPTED, high score)
        make_record(title="PhD position in Radio Astronomy (m/f/d)",
                    institution="Max Planck Institute for Radio Astronomy",
                    country="Germany", deadline=tomorrow,
                    posted_date="2026-06-01",
                    url="https://example.org/jobs/1?utm_source=x",
                    short_description="A PhD studentship on radio astronomy and "
                                      "interstellar medium magnetic fields.",
                    source="aas"),
        # 2 — genuine cosmology PhD (ACCEPTED)
        make_record(title="PhD in Cosmology",
                    institution="Leiden Observatory", country="Netherlands",
                    deadline=tomorrow2, posted_date="2026-06-10",
                    url="https://example.org/jobs/2",
                    short_description="Doctoral position in observational cosmology.",
                    source="academictransfer"),
        # 3 — genuine exoplanet PhD, no deadline (ACCEPTED and KEPT despite
        #     EXCLUDE_EXPIRED; freshness keeps it via its recent posted_date)
        make_record(title="Doctoral researcher: exoplanet atmospheres",
                    institution="NAOJ", country="Japan",
                    posted_date=(date.today() - timedelta(days=20)).isoformat(),
                    url="https://example.org/jobs/3",
                    short_description="PhD project on exoplanet atmosphere "
                                      "spectroscopy with JWST.",
                    source="jrecin"),
        # 4 — postdoc (EXCLUDED by type gate)
        make_record(title="Postdoctoral Researcher in Galaxies",
                    institution="University of Cambridge", country="UK",
                    deadline=tomorrow,
                    url="https://example.org/jobs/4",
                    short_description="Postdoc on galaxy evolution.",
                    source="jobs_ac_uk"),
        # 5 — the REAL historical leak: "Post Doctoral" used to classify as phd
        make_record(title="Post Doctoral Research Associate in Extragalactic Astronomy",
                    institution="The Open University", country="UK",
                    deadline=tomorrow,
                    url="https://example.org/jobs/5",
                    short_description="School of Physical Sciences.",
                    source="jobs_ac_uk"),
        # 6 — faculty (EXCLUDED)
        make_record(title="Assistant Professor of Astrophysics",
                    institution="MIT", country="USA",
                    url="https://example.org/jobs/6",
                    short_description="Tenure-track faculty in astrophysics.",
                    source="academicjobsonline"),
        # 7 — quantum-optics-only PhD (REJECTED: no core anchor + negatives)
        make_record(title="PhD in Quantum Optics and Photonic Circuits",
                    institution="ETH Zurich", country="Switzerland",
                    deadline=tomorrow,
                    url="https://example.org/jobs/7",
                    short_description="Doctoral position on quantum optics, "
                                      "photonics and semiconductor devices for "
                                      "quantum information.",
                    source="findaphd"),
        # 8 — context-terms-only physics PhD (REJECTED: 'theoretical' +
        #     'simulation' + 'magnetism' must NOT qualify alone)
        make_record(title="PhD in Theoretical Physics",
                    institution="TU Delft", country="Netherlands",
                    deadline=tomorrow,
                    url="https://example.org/jobs/8",
                    short_description="Theoretical and numerical simulation "
                                      "study of quantum magnetism in atomic "
                                      "spin assemblies.",
                    source="academictransfer"),
        # 9 — crossover: negative term but core anchor in TITLE (ACCEPTED)
        make_record(title="PhD: Quantum sensors for gravitational-wave detection",
                    institution="University of Hannover", country="Germany",
                    deadline=tomorrow,
                    url="https://example.org/jobs/9",
                    short_description="Doctoral project applying quantum "
                                      "optics techniques to gravitational wave "
                                      "detectors.",
                    source="euraxess"),
        # 10 — expired astro PhD (DROPPED by EXCLUDE_EXPIRED)
        make_record(title="PhD in Stellar Astrophysics",
                    institution="Uppsala University", country="Sweden",
                    deadline=yesterday,
                    url="https://example.org/jobs/10",
                    short_description="Doctoral studentship on stellar "
                                      "evolution and supernova progenitors.",
                    source="euraxess"),
        # 11 — duplicate of #1 from another board (same title+institution)
        make_record(title="PhD position in Radio Astronomy (m/f/d)",
                    institution="Max Planck Institute for Radio Astronomy",
                    country="Germany", deadline=tomorrow,
                    url="https://other.example/listing/1",
                    short_description="Radio astronomy PhD; solar physics methods.",
                    source="euraxess"),
        # 12 — ambiguous level, astro topic (kept & flagged 'unknown')
        make_record(title="Research opportunities in astrophysics",
                    institution="Some Observatory", country="Italy",
                    url="https://example.org/jobs/12",
                    short_description="Various openings in astrophysics.",
                    source="nature_careers"),
        # 13 — staff post at an astro facility (EXCLUDED by type gate)
        make_record(title="NATIONAL HIGH MAGNETIC FIELD LABORATORY NMR/MRI "
                          "DIRECTOR SEARCH",
                    institution="Florida State University", country="USA",
                    url="https://example.org/jobs/13",
                    short_description="Director search; NMR and MRI facility "
                                      "with high magnetic field magnets.",
                    source="nature_careers"),
        # 14 — postdoc whose DESCRIPTION says "must hold a PhD" (EXCLUDED —
        #      requirement phrasing must not count as PhD evidence)
        make_record(title="Research Associate in Solar Physics",
                    institution="UCL", country="UK", deadline=tomorrow,
                    url="https://example.org/jobs/14",
                    short_description="Applicants must hold a PhD in solar "
                                      "physics or a related field.",
                    source="jobs_ac_uk"),
    ]


def self_test(cfg: Config) -> int:
    """Two-pass offline test. Returns process exit code (0 = pass)."""
    print(">>> SELF-TEST (offline; no network) ...")
    tcfg = build_config(argparse.Namespace(no_config=True))
    # hermetic: pin the ASTRONOMY taxonomy + defaults so edits to config.yaml /
    # the multi-major default taxonomy can never break the pipeline self-test.
    astro_prof = load_field_profile("astronomy") if _HAVE_YAML else None
    if astro_prof:
        tcfg.core_anchors = list(astro_prof.get("core_anchors") or CORE_ANCHORS)
        tcfg.context_terms = list(astro_prof.get("context_terms") or CONTEXT_TERMS)
        tcfg.negative_terms = list(astro_prof.get("negative_terms") or NEGATIVE_TERMS)
        if isinstance(astro_prof.get("weights"), dict):
            tcfg.weights = {**tcfg.weights,
                            **{k: float(v) for k, v in astro_prof["weights"].items()
                               if k in tcfg.weights}}
        if astro_prof.get("threshold") is not None:
            tcfg.threshold = float(astro_prof["threshold"])
    else:
        tcfg.core_anchors = [t for t in CORE_ANCHORS
                             if "astronom" in t or "astrophysic" in t
                             or t in ("galaxy", "galaxies", "exoplanet",
                                      "cosmolog", "gravitational wave")]
        tcfg.context_terms = list(CONTEXT_TERMS)
        tcfg.negative_terms = list(NEGATIVE_TERMS)
        tcfg.weights = dict(RELEVANCE_WEIGHTS)
        tcfg.threshold = RELEVANCE_THRESHOLD
    tcfg.max_age_days = MAX_AGE_DAYS
    tcfg.seed_bypass_gate = True
    compile_taxonomy(tcfg)
    tcfg.output_path = cfg.stem + "_selftest"
    tcfg.countries = ["*"]            # keep geo open: test type/relevance/dedupe
    tcfg.wanted_types = ["phd"]
    tcfg.keep_ambiguous = True
    tcfg.exclude_expired = True       # sample data uses dynamic dates
    tcfg.write_html = True
    tcfg.state_path = tcfg.stem + "_state.json"   # NEVER touch the real state
    for p in (tcfg.csv_path, tcfg.json_path, tcfg.html_path, tcfg.state_path):
        if os.path.exists(p):
            os.remove(p)

    samples = _sample_records()
    # pass 1 without #2 (cosmology) and #3 (exoplanet) -> they are NEW in pass 2
    pass1 = [samples[i] for i in range(len(samples)) if i not in (1, 2)]
    print("--- pass 1 (baseline) ---")
    run(tcfg, injected_raw=pass1)

    print("--- pass 2 (full set; cosmology + exoplanet should be NEW) ---")
    r2 = run(tcfg, injected_raw=samples)

    titles = {r["title"] for r in r2}
    new_titles = {r["title"] for r in r2 if r["is_new"]}

    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        ok = ok and cond

    # --- position-type gate ---------------------------------------------
    check("Postdoctoral Researcher in Galaxies" not in titles,
          "postdoc excluded")
    check(not any(t.startswith("Post Doctoral") for t in titles),
          "'Post Doctoral Research Associate' NOT misclassified as phd "
          "(the historical leak)")
    check("Assistant Professor of Astrophysics" not in titles,
          "faculty excluded")
    check(not any("DIRECTOR SEARCH" in t for t in titles),
          "staff/director post excluded")
    check("Research Associate in Solar Physics" not in titles,
          "postdoc with 'must hold a PhD' in description excluded")

    # --- relevance engine -------------------------------------------------
    check("PhD in Quantum Optics and Photonic Circuits" not in titles,
          "quantum-optics-only post REJECTED (no core anchor)")
    check("PhD in Theoretical Physics" not in titles,
          "context-terms-only post REJECTED ('theoretical'/'simulation'/"
          "'magnetism' cannot qualify alone)")
    check("PhD position in Radio Astronomy (m/f/d)" in titles,
          "ISM/radio astronomy PhD ACCEPTED")
    check("PhD in Cosmology" in titles,
          "cosmology PhD ACCEPTED")
    check("Doctoral researcher: exoplanet atmospheres" in titles,
          "exoplanet PhD ACCEPTED")
    check("PhD: Quantum sensors for gravitational-wave detection" in titles,
          "crossover kept: title core anchor overrides negative terms")

    # --- deadlines ---------------------------------------------------------
    check("PhD in Stellar Astrophysics" not in titles,
          "expired post dropped (deadline yesterday)")
    exo = next((r for r in r2 if r["title"].startswith("Doctoral researcher")), None)
    check(exo is not None and exo.get("deadline") is None,
          "no-deadline post KEPT despite EXCLUDE_EXPIRED")

    # --- scoring & ordering -----------------------------------------------
    radio = next((r for r in r2 if r["title"].startswith("PhD position in Radio")), None)
    check(radio is not None and radio["relevance_score"] >= 8,
          f"title anchors score high (radio astronomy = "
          f"{radio['relevance_score'] if radio else '?'})")
    scores = [r["relevance_score"] for r in r2]
    check(scores == sorted(scores, reverse=True),
          "results sorted by relevance (highest first)")
    check(all(r["relevance_score"] >= tcfg.threshold and r["matched_anchors"]
              for r in r2),
          "every kept record clears threshold AND has >=1 core anchor")

    # --- dedupe / NEW / schema ----------------------------------------------
    check(radio is not None and "; " in (radio["source"] or ""),
          "cross-source duplicate merged (sources combined)")
    url_dups = dedupe_records([
        make_record(title="PhD in cosmology X", institution="Swansea",
                    url="https://ex.org/j/9?utm_source=a", source="euraxess"),
        make_record(title="PhD in cosmology X", institution=None,
                    url="https://ex.org/j/9", source="seed_urls"),
    ])
    check(len(url_dups) == 1 and url_dups[0]["institution"] == "Swansea"
          and "seed_urls" in url_dups[0]["source"],
          "same-URL duplicate merged (URL-first dedupe pass; richer "
          "institution wins)")
    check(new_titles == {"PhD in Cosmology",
                         "Doctoral researcher: exoplanet atmospheres"},
          f"exactly the two added entries are NEW (got {sorted(new_titles)})")
    amb = next((r for r in r2 if r["title"].startswith("Research opportunities")), None)
    check(amb is not None and amb["position_type"] == "unknown",
          "ambiguous level kept & flagged as 'unknown'")
    check(all(set(OUTPUT_FIELDS).issubset(r.keys()) for r in r2),
          "every record has the full output schema")
    check(os.path.exists(tcfg.html_path)
          and os.path.getsize(tcfg.html_path) > 5000,
          "results dashboard (.html) written")

    # --- career toolkit ------------------------------------------------------
    if radio is not None:
        subj, body = build_email(radio)
        check(radio["title"] in subj and "Max Planck" in subj,
              "email subject carries position title + institution")
        check("Faraday" in body or "cosmic-ray" in body,
              "email fit paragraph tailored to a radio/magnetism position")
        check(APPLICANT_PROFILE["name"] in body
              and APPLICANT_PROFILE["email"] in body,
              "email signed with applicant profile")
    check(all(p.get("name") and p.get("affiliation") and p.get("topics")
              for p in PROFESSOR_SEED),
          f"professor seed list complete ({len(PROFESSOR_SEED)} entries)")
    check(all(s.get("name") and s.get("url") and s.get("fit")
              for s in SCHOLARSHIPS),
          f"scholarship list complete ({len(SCHOLARSHIPS)} programs)")
    check(len(UNIVERSITY_DEPARTMENTS) >= 80 and
          all(len(e) == 4 and e[2].startswith("http")
              for e in UNIVERSITY_DEPARTMENTS),
          f"university registry well-formed ({len(UNIVERSITY_DEPARTMENTS)} depts)")

    # --- freshness layer (see the ADDENDUM in the docs) -----------------------
    check(all(r.get("freshness") and r.get("effective_date") for r in r2),
          "pipeline stamps freshness + effective_date on every record")
    today = date.today()
    fstate: dict = {"urls": {}, "seed_domains": {}}

    def _fresh_rec(url, **kw):
        return make_record(title="PhD in stellar astrophysics",
                           institution="U", url=url, source="test", **kw)

    r_old = _fresh_rec("https://ex.org/f/old",
                       posted_date=(today - timedelta(days=540)).isoformat())
    r_old_dl = _fresh_rec("https://ex.org/f/olddl",
                          posted_date=(today - timedelta(days=540)).isoformat(),
                          deadline=(today + timedelta(days=30)).isoformat())
    r_undated = _fresh_rec("https://ex.org/f/undated")
    r_month = _fresh_rec("https://ex.org/f/new",
                         posted_date=(today - timedelta(days=10)).isoformat())
    fkept = apply_freshness([r_old, r_old_dl, r_undated, r_month], tcfg, fstate)
    fkept_urls = {r["url"] for r in fkept}
    check("https://ex.org/f/old" not in fkept_urls,
          "18-month-old post with NO deadline DROPPED as stale")
    check("https://ex.org/f/olddl" in fkept_urls
          and r_old_dl["freshness"] == "deadline",
          "the same old post WITH a future deadline KEPT (freshness=deadline)")
    check("https://ex.org/f/undated" in fkept_urls
          and r_undated["freshness"] == "undated_new",
          "undated post KEPT on first discovery (freshness=undated_new)")
    check("https://ex.org/f/new" in fkept_urls
          and r_month["freshness"] == "posted" and r_month["age_days"] == 10,
          "post from this month KEPT (freshness=posted, age_days computed)")
    ukey = normalize_url("https://ex.org/f/undated")
    check(fstate["urls"].get(ukey, {}).get("first_seen") == today.isoformat(),
          "state file records first_seen for the undated post")
    later = today + timedelta(days=401)
    fkept2 = apply_freshness([_fresh_rec("https://ex.org/f/undated")],
                             tcfg, fstate, today=later)
    check(not fkept2,
          "the undated post is DROPPED on a simulated run 401 days later "
          "(aged out via its first-seen date)")

    # --- seed URL ingestion: JSON-LD JobPosting fixture ------------------------
    fixture = """<!doctype html><html><head>
      <title>Fallback title — Some Board</title>
      <meta property="og:title" content="OG title (must lose to JSON-LD)">
      <meta property="og:site_name" content="Some Board">
      <script type="application/ld+json">
      {"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": []},
        {"@type": "JobPosting",
         "title": "PhD position in interstellar magnetic fields (f/m/d)",
         "hiringOrganization": {"@type": "Organization",
                                "name": "Example Institute for Astrophysics"},
         "jobLocation": [{"@type": "Place",
                          "address": {"@type": "PostalAddress",
                                      "addressLocality": "Bonn",
                                      "addressCountry": "DE"}}],
         "datePosted": "2026-06-15",
         "validThrough": "2026-09-30T23:59",
         "description": "<p>Doctoral project on <b>Faraday rotation</b> and the interstellar medium of nearby galaxies.</p>"}]}
      </script></head>
      <body><main>Apply by the deadline. Posted on 15 June 2026.</main></body>
      </html>"""
    srec = parse_position_page(fixture, "https://ex.org/jobs/42", "seed_urls")
    check(srec is not None
          and srec["title"] == "PhD position in interstellar magnetic fields (f/m/d)"
          and srec["institution"] == "Example Institute for Astrophysics"
          and srec["deadline"] == "2026-09-30"
          and srec["posted_date"] == "2026-06-15"
          and srec.get("_parsed_from") == "jsonld",
          "JSON-LD JobPosting parsed from HTML fixture (title/org/dates, "
          "@graph unwrapped, JSON-LD beats og:title)")
    check(srec is not None and canonical_country(srec.get("raw_location")
          or "") in ("Germany", None) and "Bonn" in (srec.get("raw_location") or ""),
          "JobPosting jobLocation flattened (locality + ISO country)")
    ogrec = parse_position_page(
        "<html><head><title>t</title>"
        "<meta property='og:title' content='PhD studentship in cosmology'>"
        "<meta property='og:description' content='CMB analysis project.'>"
        "</head><body><p>Apply by: 15 August 2099.</p></body></html>",
        "https://ex.org/jobs/43")
    check(ogrec is not None and ogrec["title"] == "PhD studentship in cosmology"
          and ogrec["deadline"] == "2099-08-15",
          "OpenGraph/meta fallback parses title + textual deadline")

    # --- seed gate-bypass flag: a seed that is actually a postdoc --------------
    def _postdoc_seed():
        r = make_record(title="Postdoctoral fellow in galactic magnetism",
                        institution="X", country="Germany",
                        url="https://ex.org/seed/pd", source="seed_urls",
                        short_description="Postdoc on magnetic fields "
                                          "in galaxies.")
        r["_seed"] = True
        return r

    tcfg.seed_bypass_gate = True
    bypass_kept = filter_records([_postdoc_seed()], tcfg)
    check(len(bypass_kept) == 1
          and bypass_kept[0]["position_type"] == "postdoc",
          "postdoc seed KEPT under seed_bypass_gate=True (honestly labelled "
          "postdoc, not misclassified)")
    tcfg.seed_bypass_gate = False
    check(not filter_records([_postdoc_seed()], tcfg),
          "the same postdoc seed DROPPED under seed_bypass_gate=False "
          "(normal filters)")
    tcfg.seed_bypass_gate = True

    # --- supervisor aggregation: repeated senior author beats one-offs ---------
    def _doc(title, year, authors, affs):
        return {"title": title, "year": year, "authors": authors,
                "affs": affs, "orcids": [], "bibcode": None}

    sdocs = [
        _doc("Magnetic fields in M31", 2025,
             ["Student, A.", "Senior, Prof."],
             ["Univ. Bonn, Germany", "MPIfR, Bonn, Germany"]),
        _doc("Faraday rotation of M33", 2024,
             ["Other, B.", "Senior, P."],
             ["Univ. Koeln, Germany", "MPIfR, Bonn, Germany"]),
        _doc("Cosmic-ray transport in spirals", 2023,
             ["Senior, P.", "Someone, E."],
             ["MPIfR, Bonn, Germany", "IRAP, Toulouse, France"]),
        _doc("Dust polarization survey", 2026,
             ["Oneoff, C.", "Abroad, F."],
             ["AIP, Potsdam, Germany", "IAP, Paris, France"]),
        _doc("Magnetised outflows", 2025,
             ["First, G.", "Abroad, F."],
             ["Univ. Hamburg, Germany", "IAP, Paris, France"]),
    ]
    ranked = aggregate_supervisors(sdocs, "Germany",
                                   ["magnetic field", "Faraday rotation"],
                                   min_papers=2)
    names = [r["name"] for r in ranked]
    check(bool(ranked) and ranked[0]["name"] == "Senior, Prof."
          and ranked[0]["papers"] == 3 and ranked[0]["last_author_papers"] == 2,
          "supervisor ranking: repeated senior author on top (3 papers, "
          "2x last author, name variants merged)")
    check("Oneoff, C." not in names,
          "one-off author dropped (below min_papers)")
    check(all(r["name"] != "Abroad, F." for r in ranked),
          "2-paper author OUTSIDE the target country excluded "
          "(affiliation-country filter)")
    check(bool(ranked) and "MPIfR" in (ranked[0]["institution"] or "")
          and "Germany" == ranked[0]["country"],
          "top candidate carries most-common affiliation + country")

    # --- supervisor sources: OpenAlex serves non-astro majors, ADS the rest --
    check(_CANON_TO_ISO2.get("Germany") == "DE"
          and _CANON_TO_ISO2.get("United States") == "US",
          "canonical country -> ISO2 reverse map (OpenAlex country filter)")
    astro_cfg = build_config(argparse.Namespace(no_config=True))
    econ_cfg = build_config(argparse.Namespace(no_config=True))
    econ_cfg.supervisor_source = "auto"          # non-astro profile semantics
    econ_cfg.supervisor_ads_db = "general"
    check(_supervisor_chain(astro_cfg, token=False) == ["openalex", "arxiv"]
          and _supervisor_chain(astro_cfg, token=True) == ["ads", "openalex"],
          "auto source chain: astronomy -> ADS (when token) else OpenAlex")
    check(_supervisor_chain(econ_cfg, token=False) == ["openalex", "arxiv"]
          and _supervisor_chain(econ_cfg, token=True) == ["openalex", "arxiv"],
          "auto source chain: economics -> OpenAlex (ADS can't index econ)")
    oa_cfg = build_config(argparse.Namespace(no_config=True))
    oa_cfg.supervisor_source = "openalex"
    check(_supervisor_chain(oa_cfg, token=True) == ["openalex"],
          "forced supervisor_source=openalex uses OpenAlex only")
    # author_search link is source-appropriate (OpenAlex fmt is not ADS)
    ranked_oa = aggregate_supervisors(
        sdocs, None, ["magnetic field"], min_papers=2,
        search_fmt=AUTHOR_SEARCH_FMT["openalex"])
    check(bool(ranked_oa)
          and "openalex.org" in ranked_oa[0]["author_search"],
          "author_search link follows the chosen source (OpenAlex)")
    # OpenAlex per-author country codes must exclude a FRANCE-based author
    # even though the (work-level) search was anchored on Germany
    oa_docs = [
        {"title": "T1", "year": 2025, "authors": ["Doe, J.", "Schmidt, A."],
         "affs": ["Univ. Paris, France", "LMU Munich, Germany"],
         "orcids": [], "author_countries": [["FR"], ["DE"]], "bibcode": None},
        {"title": "T2", "year": 2024, "authors": ["Doe, J.", "Mueller, B."],
         "affs": ["Univ. Paris, France", "TU Berlin, Germany"],
         "orcids": [], "author_countries": [["FR"], ["DE"]], "bibcode": None},
    ]
    oa_ranked = aggregate_supervisors(oa_docs, "Germany",
                                      ["machine learning"], min_papers=1)
    oa_names = [r["name"] for r in oa_ranked]
    check(all(r != "Doe, J." for r in oa_names),
          "OpenAlex per-author country codes exclude the France-based author "
          "from a Germany search")
    check(any(r == "Schmidt, A." for r in oa_names),
          "OpenAlex per-author country codes keep the Germany-based author")
    # supervisor_senior_signal=none (economics/finance order alphabetically):
    # no last-author score bonus in the paper-aggregation path either.
    ranked_none = aggregate_supervisors(sdocs, "Germany",
                                        ["magnetic field"], min_papers=2,
                                        senior_weight=0.0)
    check(ranked_none and abs(ranked_none[0]["score"] - 3.0) < 0.001,
          "supervisor_senior_signal=none removes the last-author score bonus "
          "(alphabetical economics/finance author order)")

    # --- author-direct supervisor finder (OpenAlex topics) ---------------------
    check(_oa_field_id("https://openalex.org/fields/20") == "20"
          and _oa_field_id("fields/31") == "31" and _oa_field_id("16") == "16"
          and _oa_field_id("banana") is None,
          "OpenAlex field-id normalization (URL / fields/N / bare digits)")
    focus_cfg = build_config(argparse.Namespace(no_config=True))
    focus_cfg.subfield = "econ"
    focus_cfg.subfields = {"econ": {"keywords": ["a"], "topics": ["T111"]}}
    label, kws, tp = _supervisor_focus(focus_cfg)
    check(label == "econ" and kws == ["a"] and tp == ["T111"],
          "subfield supervisor topics win over the whole-major list")
    focus_cfg.subfield = "econ"
    focus_cfg.subfields = {"econ": {"keywords": ["a"]}}
    focus_cfg.supervisor_topics = ["T1", "T2"]
    _, _, tp2 = _supervisor_focus(focus_cfg)
    check(tp2 == ["T1", "T2"],
          "unmapped subfield falls back to the whole-major supervisor topics")

    class _FakeResp:
        def __init__(self, payload):
            self.status_code = 200
            self._p = payload
        def json(self):
            return self._p

    class _FakeHttp:
        """Serves OpenAlex works/authors fixtures, routed by filter prefix."""
        def __init__(self, pool_works, author_records, recent_by_author):
            self.pool_works = pool_works
            self.author_records = author_records
            self.recent_by_author = recent_by_author
        def raw_get(self, url, params=None, **kw):
            params = params or {}
            filt = params.get("filter") or ""
            if filt.startswith("openalex_id:"):
                return _FakeResp({"meta": {}, "results": self.author_records})
            if filt.startswith("author.id:"):
                aid = filt.split("author.id:")[1].split(",")[0].rstrip("/")
                return _FakeResp({"meta": {},
                                  "results": self.recent_by_author.get(aid, [])})
            if filt.startswith("authorships.countries:"):
                return _FakeResp({"meta": {"count": len(self.pool_works)},
                                  "results": self.pool_works})
            return None

    FIELD20 = {"field": {"id": "https://openalex.org/fields/20"}}

    def _author(aid, name, h, cited, inst, topics):
        return {"id": f"https://openalex.org/{aid}", "display_name": name,
                "orcid": f"https://orcid.org/0000-{aid}", "works_count": 50,
                "cited_by_count": cited, "summary_stats": {"h_index": h},
                "affiliations": [
                    {"institution": {"display_name": inst,
                                     "country_code": "GB",
                                     "type": "education"},
                     "years": [2022, 2023, 2024, 2025]}],
                "last_known_institutions": [
                    {"display_name": inst, "country_code": "GB"}],
                "topics": [{"id": f"https://openalex.org/{t}",
                            "display_name": t} for t in topics]}

    def _work(wid, title, year, cand_id, cand_pos, cand_corr, cand_cty,
              cand_inst_cty=None, cand_inst_name=None):
        head = ([{"author": {"id": "https://openalex.org/O1"},
                  "author_position": "first", "is_corresponding": False,
                  "countries": ["GB"]}] if cand_pos != "first" else [])
        return {"id": f"https://openalex.org/{wid}",
                "doi": f"https://doi.org/10.1/{wid}", "title": title,
                "publication_year": year, "primary_topic": FIELD20,
                "authorships": head + [
                    {"author": {"id": f"https://openalex.org/{cand_id}"},
                     "author_position": cand_pos,
                     "is_corresponding": cand_corr, "countries": cand_cty,
                     "institutions": [{"display_name": cand_inst_name,
                                       "country_code": cand_inst_cty}]
                     if cand_inst_cty else []}]}

    # Candidate pool (works query): Ada Grace publishes 2 in-country works,
    # Dana Fox 2 of her 5, Cal Diaz 2 (but is inactive), Bo Lin none.
    pool_works = [
        _work("W1", "Recent macro paper", 2025, "A1", "last", True, ["GB"],
              "GB", "London School of Economics"),
        _work("W2", "Another macro paper", 2024, "A1", "first", False, ["GB"],
              "GB", "London School of Economics"),
        _work("W20", "US finance paper", 2024, "A2", "first", False, ["US"],
              "US", "US Institute"),
        _work("W31", "German econ paper", 2024, "A3", "last", True, ["GB"],
              "GB", "Some Institute"),
        _work("W32", "Another German econ paper", 2023, "A3", "first", False,
              ["GB"], "GB", "Some Institute"),
        _work("W41", "US paper one", 2024, "A4", "first", False, ["US"],
              "US", "Foreign University"),
        _work("W42", "US paper two", 2024, "A4", "first", False, ["US"],
              "US", "Foreign University"),
        _work("W43", "US paper three", 2024, "A4", "first", False, ["US"],
              "US", "Foreign University"),
        _work("W44", "UK-network paper", 2023, "A4", "first", False,
              ["GB"], "GB", "UK Research Network"),
        _work("W45", "Another UK-network paper", 2023, "A4", "first", False,
              ["GB"], "GB", "UK Research Network"),
    ]
    recent_by_author = {
        "https://openalex.org/A1": [pool_works[0], pool_works[1]],
        "https://openalex.org/A4": pool_works[5:10],
        # A2 never reaches enrichment (no GB works); A3 -> [] (inactive).
    }
    author_records = [
        _author("A1", "Ada Grace", 40, 9000, "London School of Economics",
                ["T1"]),
        _author("A2", "Bo Lin", 20, 8000, "Bank of England", ["T2"]),
        _author("A3", "Cal Diaz", 5, 1000, "Some Institute", ["T1"]),
        _author("A4", "Dana Fox", 15, 2000, "Foreign University", ["T1"]),
    ]
    ad_http = _FakeHttp(pool_works, author_records, recent_by_author)
    ad_cfg = build_config(argparse.Namespace(no_config=True))
    ad_cfg.supervisor_years_back = 5
    ad_cfg.supervisor_senior_signal = "last_author"
    ad_rows = openalex_supervisor_authors(ad_cfg, ad_http, ["T1", "T2"],
                                          "United Kingdom", "20")
    ad_names = [r["name"] for r in ad_rows]
    check(len(ad_rows) == 1
          and ad_rows[0]["name"] == "Ada Grace"
          and ad_rows[0]["score"] == 44.0   # h40 + 2 recent + 2 in-country
          and ad_rows[0]["institution"] == "London School of Economics"
          and ad_rows[0]["orcid"] == "0000-A1"
          and ad_rows[0]["orcid_link"] == "https://orcid.org/0000-A1"
          and ad_rows[0]["author_search"] == "https://openalex.org/A1"
          and ad_rows[0]["last_author_papers"] == 1
          and ad_rows[0]["topics"] == "T1",
          "author-direct finder: country-verified works pool + h-index/recency/"
          "in-country scoring, rows shaped for the pipeline")
    check(all(r != "Bo Lin" for r in ad_names),
          "author-direct finder drops a candidate who never publishes from "
          "the target country (works-pool gate)")
    check(all(r != "Dana Fox" for r in ad_names),
          "author-direct finder drops a candidate whose recent works are "
          "mostly elsewhere even if two CEPR-style UK-network papers passed "
          "the pool (majority in-country rule)")
    check(all(r != "Cal Diaz" for r in ad_names),
          "author-direct finder drops candidates with no recent papers "
          "(inactive)")

    # --- field profile from YAML changes what qualifies ------------------------
    if _HAVE_YAML:
        import tempfile
        marine_yaml = (
            "name: marine_test\n"
            "core_anchors: [marine biolog, coral reef, oceanograph]\n"
            "context_terms: [field work]\n"
            "negative_terms: [astronomy]\n"
            "search_terms: [marine biology]\n"
            "supervisor_field: 27\n"
            "supervisor_topics: [T10077, T10581]\n"
            "supervisor_senior_signal: corresponding\n"
            "threshold: 2.0\n"
            "subfields:\n"
            "  reefs: {label: Reefs, keywords: [coral reef]}\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                         encoding="utf-8") as tf:
            tf.write(marine_yaml)
            tmp_path = tf.name
        try:
            prof = _load_yaml_file(tmp_path)
            mcfg = build_config(argparse.Namespace(no_config=True))
            apply_field_profile(mcfg, prof or {})
            compile_taxonomy(mcfg)
            check(mcfg.supervisor_field == "27"
                  and mcfg.supervisor_topics == ["T10077", "T10581"]
                  and mcfg.supervisor_senior_signal == "corresponding",
                  "field profile loads supervisor_field/topics/senior_signal "
                  "(author-direct wiring)")
            pname, subname, pprof = resolve_field_arg("econometrics")
            check(pname == "economics" and subname == "econometrics"
                  and pprof is not None
                  and any(t for t in pprof.get("subfields",
                          {}).get("econometrics", {}).get("topics") or []),
                  "resolve_field_arg finds a subfield of a NON-default profile "
                  "(--field econometrics -> economics/econometrics, topics "
                  "reachable for the author-direct supervisor search)")
            coral_title = "PhD position in coral reef bleaching"
            m_score, m_anchors, _, _ = score_relevance(coral_title, "", mcfg)
            a_score, a_anchors, _, _ = score_relevance(coral_title, "", tcfg)
            check(is_relevant(m_score, m_anchors, mcfg)
                  and not is_relevant(a_score, a_anchors, tcfg),
                  "YAML field profile changes what qualifies (coral-reef PhD "
                  "passes under marine profile, fails under astronomy)")
            astro_title = "PhD in radio astronomy"
            ma_score, ma_anchors, _, _ = score_relevance(astro_title, "", mcfg)
            check(not is_relevant(ma_score, ma_anchors, mcfg),
                  "astronomy post does NOT qualify under the marine profile")
            check("reefs" in mcfg.subfields,
                  "profile subfields loaded (supervisor finder wiring)")

            # require_title_anchor: desc-only core matches must NOT qualify
            cs_yaml = (
                "name: cs_test\n"
                "core_anchors: [computer vision, machine learning, deep learning]\n"
                "context_terms: [data science]\n"
                "negative_terms: []\n"
                "search_terms: [computer science]\n"
                "require_title_anchor: true\n"
                "threshold: 2.0\n")
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                             encoding="utf-8") as tf:
                tf.write(cs_yaml)
                cs_tmp = tf.name
            try:
                ccfg = build_config(argparse.Namespace(no_config=True))
                apply_field_profile(ccfg, _load_yaml_file(cs_tmp) or {})
                compile_taxonomy(ccfg)
                # ML-heavy ASTRO post: strong description match, no title match
                cs_astro_desc = ("PhD position in astrophysics", (
                    "Apply deep learning and machine learning with neural "
                    "networks to classify galaxies from imaging surveys."))
                s, anc, _, _ = score_relevance(*cs_astro_desc, ccfg)
                ttl = [t for t, rx in ccfg._core_rx
                       if rx.search(cs_astro_desc[0])]
                check(not is_relevant(s, anc, ccfg, title_anchors=ttl),
                      "require_title_anchor: ML-heavy astrophysics post with no "
                      "CS keyword in the title is REJECTED (desc-only match)")
                # genuine CS post: title anchor present -> still qualifies
                cs_real = ("PhD student in computer vision", (
                    "Develop deep learning models for medical image "
                    "segmentation."))
                s2, anc2, _, _ = score_relevance(*cs_real, ccfg)
                ttl2 = [t for t, rx in ccfg._core_rx if rx.search(cs_real[0])]
                check(is_relevant(s2, anc2, ccfg, title_anchors=ttl2),
                      "require_title_anchor: real CS title still qualifies")
            finally:
                os.unlink(cs_tmp)
        finally:
            os.unlink(tmp_path)
    else:
        check(True, "PyYAML not installed — YAML profile checks skipped "
                    "(built-in defaults in use)")

    print(">>> SELF-TEST:", "ALL PASSED" if ok else "FAILURES PRESENT")
    return 0 if ok else 1
