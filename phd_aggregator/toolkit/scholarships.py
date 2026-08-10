"""toolkit.scholarships — the curated, profile-matched scholarship list
(migration Step 10). Extracted verbatim from phd_aggregator.py.

Writes scholarships.md + scholarships.csv for the applicant's situation
(Iranian citizen, M.Sc. in hand, astronomy/astrophysics, targets Europe /
Japan / China). Deadline windows are the usual annual pattern.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from core.config import Config

log = logging.getLogger("phd_aggregator")

SCHOLARSHIPS: list[dict] = [
    # --- Germany ---------------------------------------------------------------
    dict(name="IMPRS for Astronomy & Astrophysics (Bonn/Cologne, MPIfR)",
         region="Germany", deadline="~mid-November (autumn start)",
         funding="full PhD funding (support contract/stipend)",
         url="https://imprs-astro.mpifr-bonn.mpg.de/",
         fit="STRONGEST FIT — radio astronomy & cosmic magnetism at MPIfR; "
             "your co-author Rainer Beck's institute, S.A. Mao's group"),
    dict(name="IMPRS on Astrophysics (Garching: MPA/MPE/ESO/LMU)",
         region="Germany", deadline="~1 November",
         funding="full PhD funding", url="https://www.imprs-astro.mpg.de/",
         fit="ISM/magnetism theory (MPA) + observations (MPE), ESO co-location"),
    dict(name="IMPRS-HD (Heidelberg)", region="Germany", deadline="~November",
         funding="full PhD funding", url="https://www.imprs-hd.mpg.de/",
         fit="star formation / ISM groups (ITA, MPIA)"),
    dict(name="DAAD Research Grants — Doctoral Programmes in Germany",
         region="Germany", deadline="portal opens ~Aug, closes Sep–Nov",
         funding="~€1,300/month + insurance + travel",
         url="https://www.daad.de/en/studying-in-germany/scholarships/",
         fit="Iranian citizens eligible; combine with a German host professor "
             "(Hamburg/Bochum/Bonn radio-astro groups)"),
    # --- EU-wide ----------------------------------------------------------------
    dict(name="Marie Skłodowska-Curie Doctoral Networks (MSCA DN)",
         region="EU-wide", deadline="per-network, year-round",
         funding="salaried DC position (~€3,400/month gross, country-corrected)",
         url="https://marie-sklodowska-curie-actions.ec.europa.eu/",
         fit="no nationality restriction; you satisfy the mobility rule; "
             "openings appear in this aggregator via EURAXESS"),
    # --- Switzerland / France ----------------------------------------------------
    dict(name="Swiss Government Excellence Scholarships",
         region="Switzerland", deadline="Aug–Dec via Swiss embassy in Tehran",
         funding="CHF 1,920/month + fees + insurance",
         url="https://www.sbfi.admin.ch/sbfi/en/home/education/scholarships-and-grants/swiss-government-excellence-scholarships.html",
         fit="Iran is on the country list; hosts incl. Geneva/ETH/EPFL astro"),
    dict(name="Eiffel Excellence Scholarship (PhD stream)",
         region="France", deadline="host applies; internal deadlines ~Dec, final ~Jan",
         funding="€1,700/month (12-month PhD stays)",
         url="https://www.campusfrance.org/en/the-eiffel-scholarship-program-of-excellence",
         fit="approach IRAP/IAP/IAS/LAM professors first — the INSTITUTION nominates you"),
    dict(name="Doctoral contracts, ED 127 Astronomy & Astrophysics Île-de-France",
         region="France", deadline="spring campaign (~April–May)",
         funding="3-year salaried doctoral contract",
         url="https://ed127.obspm.fr/",
         fit="covers Observatoire de Paris, IAP, IAS, CEA — ISM/plasma groups"),
    # --- Italy / Spain / Hungary ---------------------------------------------------
    dict(name="SISSA PhD in Astrophysics & Cosmology",
         region="Italy", deadline="spring call (~March–June)",
         funding="4-year fellowship, no fees",
         url="https://www.sissa.it/research/astrophysics-cosmology",
         fit="Ntormousi's ISM-magnetism group is at SNS Pisa nearby; SISSA hosts "
             "galactic magnetism theory"),
    dict(name="GSSI PhD scholarships (astroparticle physics)",
         region="Italy", deadline="~June",
         funding="scholarship + accommodation", url="https://www.gssi.it/",
         fit="cosmic-ray physics angle of your profile"),
    dict(name="Italian university PhD calls (all funded since DM 226/2021)",
         region="Italy", deadline="April–July per university",
         funding="~€1,195/month scholarships",
         url="https://fisica-astronomia.unibo.it/en",
         fit="Bologna (Vazza/Bonafede cosmic magnetism!), Padova, INAF-funded themes"),
    dict(name="“la Caixa” INPhINIT Incoming Fellowships",
         region="Spain/Portugal", deadline="~late January",
         funding="~€35,800/year, 3 years",
         url="https://lacaixafellowships.org/",
         fit="any nationality; hosts include IAC, IAA-CSIC (radio/AMIGA), ICE"),
    dict(name="Stipendium Hungaricum", region="Hungary",
         deadline="November – 15 January",
         funding="full tuition + stipend + housing support",
         url="https://stipendiumhungaricum.hu/",
         fit="Iran is a partner country; ELTE + Konkoly Observatory host astro PhDs"),
    # --- United Kingdom -------------------------------------------------------------
    dict(name="Gates Cambridge Scholarship", region="United Kingdom",
         deadline="early December (international round)",
         funding="full cost of PhD + stipend",
         url="https://www.gatescambridge.org/",
         fit="any nationality; apply alongside Cambridge IoA/Cavendish astro PhD"),
    dict(name="Clarendon Fund (Oxford)", region="United Kingdom",
         deadline="automatic with course application (Dec–Jan)",
         funding="fees + living stipend", url="https://www.ox.ac.uk/clarendon",
         fit="no separate application — just apply to Oxford Astrophysics on time"),
    dict(name="Imperial President's PhD Scholarships", region="United Kingdom",
         deadline="rounds ~Nov / Jan / Mar",
         funding="fees + £25k/yr stipend",
         url="https://www.imperial.ac.uk/study/fees-and-funding/postgraduate/presidents-phd-scholarships/",
         fit="Imperial astrophysics group"),
    dict(name="STFC-funded studentships (via departments)",
         region="United Kingdom", deadline="Dec–Feb with course applications",
         funding="fees + stipend (~£19k/yr)",
         url="https://www.ukri.org/councils/stfc/",
         fit="international students eligible since 2021 (max ~30% quota) — "
             "target JBCA Manchester (radio!), Cardiff, Portsmouth ICG"),
    # --- Japan -----------------------------------------------------------------------
    dict(name="MEXT Japanese Government Scholarship (Embassy track)",
         region="Japan", deadline="Tehran embassy screening ~April–June",
         funding="tuition + ~¥145,000/month + airfare",
         url="https://www.studyinjapan.go.jp/en/planning/scholarship/",
         fit="the standard fully-funded route into U. Tokyo/Kyoto/Tohoku astro; "
             "also a University-recommendation track ~Oct–Dec"),
    dict(name="SOKENDAI (NAOJ) PhD, Astronomical Science",
         region="Japan", deadline="entrance exams ~Oct & ~Jan",
         funding="RA-ships + fee waivers commonly cover students",
         url="https://guas-astronomy.jp/eng/",
         fit="PhD physically at NAOJ — SKA-Japan / Faraday-tomography people "
             "(T. Akahori); English program"),
    dict(name="IGPAS — Tohoku University International Graduate Program",
         region="Japan", deadline="~November–January",
         funding="MEXT-funded slots for top applicants",
         url="https://www.sci.tohoku.ac.jp/english/",
         fit="Astronomical Institute (galactic astronomy) with English admission"),
    # --- China ------------------------------------------------------------------------
    dict(name="CSC Chinese Government Scholarship (Type B, university track)",
         region="China", deadline="January–April",
         funding="tuition + ~¥3,500/month + housing",
         url="https://www.campuschina.org/",
         fit="Iranians eligible; pair with KIAA-PKU, Nanjing, Tsinghua astro"),
    dict(name="ANSO Scholarship for Young Talents",
         region="China", deadline="~31 March",
         funding="full PhD at CAS institutes (via UCAS)",
         url="https://www.anso.org.cn/programmes/talents/",
         fit="NAOC/PMO/SHAO — FAST + Galactic magnetism (JinLin Han's institute)"),
    dict(name="CAS-TWAS President's PhD Fellowship",
         region="China", deadline="~March–April",
         funding="full PhD at CAS institutes",
         url="https://twas.org/opportunity/cas-twas-presidents-phd-fellowship-programme",
         fit="explicitly for developing-country nationals incl. Iran"),
    # --- pan-European bonus --------------------------------------------------------------
    dict(name="ESO Studentship Programme (Garching)",
         region="Germany/Chile", deadline="rounds ~May & ~November",
         funding="up to 2 years at ESO during your PhD",
         url="https://recruitment.eso.org/",
         fit="combine with ANY European PhD enrolment — ESO already feeds "
             "this aggregator"),
]

_SCHOLARSHIP_PRACTICAL_NOTES = """\
## Practical notes for applying from Iran

* **Language tests**: nearly everything above wants IELTS/TOEFL — book early;
  several IMPRS and Italian/Japanese programs accept a supervisor's statement
  of English proficiency instead.
* **Application fees**: most listed programs are free to apply. Where a fee
  exists (some UK unis), email the graduate office and ask for a WAIVER —
  sanctions make card payments from Iran impossible and offices know this.
* **Degree recognition**: for Germany check your Kharazmi degree in ANABIN;
  DAAD Tehran can advise. For Italy you need a "Dichiarazione di Valore" or
  CIMEA statement — start early, it is slow.
* **Visas**: salaried EU PhD positions (MSCA, ED127, Dutch/Nordic jobs) use
  national employment visas — allow 2–4 months at the embassy. MEXT and CSC
  handle visas through the program itself.
* **Timing** (as of July 2026): the big November cluster (IMPRS ×3, Gates,
  Clarendon, Stipendium Hungaricum, MEXT university track) is ~4 months away —
  contact potential supervisors NOW; the Jan–Apr cluster (INPhINIT, CSC, ANSO,
  CAS-TWAS) follows right after.
"""


def write_scholarships(cfg: Config) -> None:
    """Write scholarships.md + scholarships.csv (curated, profile-matched)."""
    out_dir = os.path.dirname(os.path.abspath(cfg.stem))
    csv_path = os.path.join(out_dir, "scholarships.csv")
    pd.DataFrame(SCHOLARSHIPS).to_csv(csv_path, index=False)

    by_region: dict[str, list[dict]] = {}
    for s in SCHOLARSHIPS:
        by_region.setdefault(s["region"], []).append(s)
    md = ["# PhD scholarships & funding matched to your profile",
          "",
          "Profile: Iranian citizen, M.Sc. Gravity & Cosmology (Kharazmi), "
          "radio astronomy / ISM magnetism / cosmic-ray research record "
          "(A&A first-author paper), targets Europe · Japan · China.",
          "",
          "Deadline windows are the *usual annual pattern* — always confirm "
          "the current year's call on the linked page.", ""]
    for region, items in by_region.items():
        md.append(f"## {region}\n")
        for s in items:
            md.append(f"### [{s['name']}]({s['url']})")
            md.append(f"- **Deadline:** {s['deadline']}")
            md.append(f"- **Funding:** {s['funding']}")
            md.append(f"- **Why it fits you:** {s['fit']}\n")
    md.append(_SCHOLARSHIP_PRACTICAL_NOTES)
    md_path = os.path.join(out_dir, "scholarships.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    log.info("[scholarships] %d programs -> %s , %s",
             len(SCHOLARSHIPS), md_path, csv_path)
