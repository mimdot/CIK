"""toolkit.professors — the curated + live-arXiv professor list (migration
Step 10). Extracted verbatim from phd_aggregator.py.

Writes professors.csv + professors.md: researchers in the applicant's fields
(curated network from the literature around their own topics) plus a live
arXiv survey of currently active authors.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional
from urllib.parse import quote

from core.csvout import write_csv

from core.config import Config
from core.deps import _HAVE_FEEDPARSER, feedparser
from core.http import Http
from core.utils import clean_oneline
from supervisors.arxiv import ARXIV_API

log = logging.getLogger("phd_aggregator")

# Curated from the literature around the applicant's own topics (Faraday
# rotation/tomography, cosmic magnetism, radio–FIR correlation, cosmic-ray
# propagation, ISM/star formation). Affiliations move — verify before writing.
PROFESSOR_SEED: list[dict] = [
    # --- your existing network (easiest doors) -------------------------------
    dict(name="Fatemeh S. Tabatabaei", affiliation="IPM, Tehran", country="Iran",
         topics="radio–FIR correlation, magnetic fields in galaxies",
         note="M.Sc./RA supervisor — ask for introductions"),
    dict(name="Mehrnoosh Tahani", affiliation="University of South Carolina", country="USA",
         topics="magnetic fields in molecular clouds, Faraday methods",
         note="current mentor (GMIMS)"),
    dict(name="Rainer Beck", affiliation="MPIfR Bonn (emeritus)", country="Germany",
         topics="galactic magnetic fields, radio polarization", note="co-author"),
    dict(name="Volker Heesen", affiliation="Universität Hamburg", country="Germany",
         topics="cosmic-ray transport, radio halos, LOFAR nearby galaxies", note="co-author"),
    dict(name="Ralf-Jürgen Dettmar", affiliation="Ruhr-Universität Bochum", country="Germany",
         topics="disk-halo interaction, radio continuum of galaxies", note="co-author"),
    dict(name="Krzysztof Chyży", affiliation="Jagiellonian University, Kraków", country="Poland",
         topics="radio–FIR relation, magnetism of galaxies", note="co-author"),
    dict(name="Timothy Shimwell", affiliation="ASTRON / Leiden", country="Netherlands",
         topics="LOFAR LoTSS surveys", note="co-author on SPARCS poster"),
    # --- Germany --------------------------------------------------------------
    dict(name="Sui Ann Mao", affiliation="MPIfR Bonn", country="Germany",
         topics="Faraday rotation, magnetism in nearby galaxies",
         note="MPIfR group leader — IMPRS Bonn/Cologne host"),
    dict(name="Marcus Brüggen", affiliation="Universität Hamburg", country="Germany",
         topics="cosmic magnetism, clusters, LOFAR", note=""),
    dict(name="Christoph Pfrommer", affiliation="AIP Potsdam", country="Germany",
         topics="cosmic-ray feedback, MHD simulations", note=""),
    dict(name="Philipp Girichidis", affiliation="Universität Heidelberg (ITA)", country="Germany",
         topics="cosmic-ray-driven ISM simulations", note=""),
    dict(name="Ralf Klessen", affiliation="Universität Heidelberg (ITA)", country="Germany",
         topics="star formation, ISM turbulence", note=""),
    dict(name="Stefanie Walch-Gassner", affiliation="Universität zu Köln", country="Germany",
         topics="SILCC ISM simulations, molecular clouds", note=""),
    dict(name="Torsten Enßlin", affiliation="MPA Garching", country="Germany",
         topics="information field theory, Faraday sky reconstruction", note=""),
    dict(name="Aritra Basu", affiliation="Thüringer Landessternwarte Tautenburg", country="Germany",
         topics="radio–FIR correlation, cosmic magnetism", note="works on YOUR exact topic"),
    # --- rest of Europe ---------------------------------------------------------
    dict(name="Marijke Haverkorn", affiliation="Radboud University", country="Netherlands",
         topics="Faraday tomography of the Milky Way, ISM magnetism", note=""),
    dict(name="Andrew Fletcher", affiliation="Newcastle University", country="United Kingdom",
         topics="galactic dynamo, turbulent magnetic fields", note=""),
    dict(name="Anna Scaife", affiliation="University of Manchester (JBCA)", country="United Kingdom",
         topics="radio astronomy, machine learning, SKA", note=""),
    dict(name="Paddy Leahy", affiliation="University of Manchester (JBCA)", country="United Kingdom",
         topics="radio polarization, GMIMS", note=""),
    dict(name="Franco Vazza", affiliation="Università di Bologna", country="Italy",
         topics="cosmic magnetism simulations, radio cosmic web", note=""),
    dict(name="Annalisa Bonafede", affiliation="Università di Bologna", country="Italy",
         topics="cluster magnetic fields, LOFAR", note=""),
    dict(name="Ettore Carretti", affiliation="INAF Bologna", country="Italy",
         topics="GMIMS / S-PASS diffuse polarization surveys", note="GMIMS!"),
    dict(name="Federica Govoni", affiliation="INAF Cagliari", country="Italy",
         topics="cluster magnetism, SKA polarization", note=""),
    dict(name="Marco Padovani", affiliation="INAF Arcetri", country="Italy",
         topics="cosmic-ray ionisation in molecular clouds", note="clouds + CRs = your niche"),
    dict(name="Daniele Galli", affiliation="INAF Arcetri", country="Italy",
         topics="star formation, magnetic fields in clouds", note=""),
    dict(name="Evangelia Ntormousi", affiliation="Scuola Normale Superiore, Pisa", country="Italy",
         topics="ISM magnetic fields, galactic dynamos (simulations)", note=""),
    dict(name="Juan Diego Soler", affiliation="INAF-IAPS Rome", country="Italy",
         topics="magnetic fields and filaments, Planck/HI", note=""),
    dict(name="Katia Ferrière", affiliation="IRAP Toulouse", country="France",
         topics="Galactic magnetic-field modelling", note=""),
    dict(name="François Boulanger", affiliation="ENS Paris", country="France",
         topics="ISM physics, dust polarization", note=""),
    # --- Japan ------------------------------------------------------------------
    dict(name="Takuya Akahori", affiliation="NAOJ / SKA-Japan", country="Japan",
         topics="Faraday tomography, intergalactic magnetic fields",
         note="SOKENDAI/NAOJ PhD route"),
    dict(name="Keitaro Takahashi", affiliation="Kumamoto University", country="Japan",
         topics="cosmic magnetism, SKA-Japan, 21cm", note=""),
    dict(name="Mami Machida", affiliation="Kyushu University (verify)", country="Japan",
         topics="MHD simulations of galactic magnetic fields", note=""),
    dict(name="Hiroyuki Nakanishi", affiliation="Kagoshima University", country="Japan",
         topics="Milky Way ISM, radio astronomy", note=""),
    dict(name="Tsutomu Takeuchi", affiliation="Nagoya University", country="Japan",
         topics="statistical astrophysics, IR/radio galaxy properties", note=""),
    # --- China ------------------------------------------------------------------
    dict(name="JinLin Han", affiliation="NAOC, Beijing", country="China",
         topics="pulsar rotation measures, Galactic magnetic-field structure",
         note="CAS PhD via UCAS (ANSO/CSC/CAS-TWAS funding)"),
    dict(name="Xiaohui Sun", affiliation="Yunnan University (SWIFAR)", country="China",
         topics="Galactic synchrotron, RM surveys, Faraday tomography", note=""),
    dict(name="Di Li", affiliation="NAOC / Tsinghua (verify)", country="China",
         topics="ISM, FAST HI and pulsars", note=""),
    dict(name="Keping Qiu", affiliation="Nanjing University", country="China",
         topics="star formation, magnetic fields (JCMT BISTRO)", note=""),
    dict(name="Hua-bai Li", affiliation="CUHK, Hong Kong", country="China",
         topics="molecular-cloud magnetic fields", note=""),
    dict(name="Xuening Bai", affiliation="Tsinghua University", country="China",
         topics="MHD and plasma astrophysics", note=""),
    # --- GMIMS / RM-community network outside the target regions ----------------
    dict(name="Bryan Gaensler", affiliation="UC Santa Cruz", country="USA",
         topics="RM grids, GMIMS PI", note="GMIMS network"),
    dict(name="Jo-Anne Brown", affiliation="University of Calgary", country="Canada",
         topics="GMIMS, Galactic RMs", note="GMIMS network"),
    dict(name="George Heald", affiliation="CSIRO", country="Australia",
         topics="GMIMS, LOFAR polarization of galaxies", note="GMIMS network"),
    dict(name="Cameron Van Eck", affiliation="ANU (verify)", country="Australia",
         topics="Faraday tomography, RM synthesis tooling", note="GMIMS network"),
    dict(name="Naomi McClure-Griffiths", affiliation="ANU", country="Australia",
         topics="HI, Milky Way magnetism", note=""),
]

PROFESSOR_ARXIV_QUERIES = [
    '"Faraday tomography"',
    '"Faraday rotation" AND "galaxies"',
    '"cosmic ray propagation" AND "galaxies"',
    '"radio-FIR correlation" OR "radio-infrared correlation"',
    '"galactic magnetic field"',
    '"magnetic fields" AND "molecular clouds"',
]


def _arxiv_author_survey(http: Http, per_query: int = 40) -> list[dict]:
    """Frequency count of authors on RECENT astro-ph papers matching the
    profile queries (official arXiv API; ~1 request per query, throttled).
    An author on >=2 matched papers is likely active in the field right now."""
    if not _HAVE_FEEDPARSER:
        log.warning("[professors] feedparser missing — skipping arXiv survey")
        return []
    counts: dict[str, dict] = {}
    for q in PROFESSOR_ARXIV_QUERIES:
        params = {"search_query": f"cat:astro-ph.GA AND all:{q}",
                  "start": 0, "max_results": per_query,
                  "sortBy": "submittedDate", "sortOrder": "descending"}
        resp = http.raw_get(ARXIV_API, params=params)
        time.sleep(1.5)                       # arXiv asks ~3s between calls
        if resp is None or resp.status_code >= 400:
            log.warning("[professors] arXiv query failed: %s", q)
            continue
        feed = feedparser.parse(resp.content)
        for entry in getattr(feed, "entries", []):
            for au in getattr(entry, "authors", []):
                name = (au.get("name") or "").strip()
                if not name:
                    continue
                slot = counts.setdefault(name, {"papers": 0, "queries": set(),
                                                "sample": None})
                slot["papers"] += 1
                slot["queries"].add(q.strip('"'))
                slot["sample"] = slot["sample"] or entry.get("title", "")
        log.info("[professors] arXiv %s -> %d entries", q,
                 len(getattr(feed, "entries", [])))
    curated = {p["name"].lower() for p in PROFESSOR_SEED}
    rows = [dict(name=n, papers=v["papers"],
                 topics="; ".join(sorted(v["queries"])),
                 sample_recent_paper=clean_oneline(v["sample"]))
            for n, v in counts.items()
            if v["papers"] >= 2 and n.lower() not in curated]
    rows.sort(key=lambda r: -r["papers"])
    return rows[:40]


def find_professors(cfg: Config, http: Optional[Http] = None) -> None:
    """Write professors.csv + professors.md: curated researchers in the
    applicant's fields plus a live arXiv survey of currently active authors."""
    out_dir = os.path.dirname(os.path.abspath(cfg.stem))

    def ads_link(name: str) -> str:
        return ('https://ui.adsabs.harvard.edu/search/q=' +
                quote(f'author:"{name}"', safe=""))

    rows = []
    for p in PROFESSOR_SEED:
        rows.append({"origin": "curated", "name": p["name"],
                     "affiliation": p["affiliation"], "country": p["country"],
                     "topics": p["topics"], "note": p["note"],
                     "recent_papers_matched": None, "ads_search": ads_link(p["name"])})
    arxiv_rows = _arxiv_author_survey(http) if http else []
    for a in arxiv_rows:
        rows.append({"origin": "arxiv", "name": a["name"], "affiliation": None,
                     "country": None, "topics": a["topics"],
                     "note": a["sample_recent_paper"],
                     "recent_papers_matched": a["papers"],
                     "ads_search": ads_link(a["name"])})

    csv_path = os.path.join(out_dir, "professors.csv")
    write_csv(csv_path, rows)

    md = ["# Professors & researchers in your fields",
          "",
          "Topics: Faraday rotation/tomography, cosmic magnetism, radio–FIR "
          "correlation, cosmic-ray propagation, ISM & star formation.",
          "Affiliations drift — click the ADS link and check the person's "
          "latest affiliation before emailing.", ""]
    md.append("## Curated (literature around your own papers/collaborations)\n")
    md.append("| Name | Affiliation | Country | Topics | Note |")
    md.append("|---|---|---|---|---|")
    for p in PROFESSOR_SEED:
        md.append(f"| [{p['name']}]({ads_link(p['name'])}) | {p['affiliation']} "
                  f"| {p['country']} | {p['topics']} | {p['note']} |")
    if arxiv_rows:
        md.append("\n## Active right now (authors on >=2 recent arXiv "
                  "astro-ph.GA papers matching your topics)\n")
        md.append("| Name | Matched papers | Topics | Example recent paper |")
        md.append("|---|---|---|---|")
        for a in arxiv_rows:
            md.append(f"| [{a['name']}]({ads_link(a['name'])}) | {a['papers']} "
                      f"| {a['topics']} | {(a['sample_recent_paper'] or '')[:90]} |")
    md_path = os.path.join(out_dir, "professors.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    log.info("[professors] %d curated + %d from arXiv -> %s , %s",
             len(PROFESSOR_SEED), len(arxiv_rows), csv_path, md_path)
