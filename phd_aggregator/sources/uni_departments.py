"""source_uni_departments — university physics/astronomy department sweep
(migration Step 5, Batch C). Sweeps the ACTIVE FIELD PROFILE's `departments:`
block, falling back to the built-in astronomy registry (UNIVERSITY_DEPARTMENTS),
and harvests links that look like doctoral openings."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import pandas as pd

from core.config import Config
from core.http import Http
from core.records import make_record
from core.utils import canonical_country, normalize_url

from .base import log, register_source


UNIVERSITY_DEPARTMENTS: list[tuple[str, str, str, bool]] = [
    # -- Germany --------------------------------------------------------------
    ("Germany", "Universität Heidelberg — IMPRS-HD (ZAH/MPIA doctoral school)",
     "https://www.imprs-hd.mpg.de/", True),
    ("Germany", "Universität Bonn — Argelander Institute for Astronomy",
     "https://www.aifa.uni-bonn.de/en", True),
    ("Germany", "LMU München — Faculty of Physics / USM",
     "https://www.physik.lmu.de/en/research/doctoral-study-and-habilitation/", False),
    ("Germany", "Universität Hamburg — Hamburger Sternwarte",
     "https://www.physik.uni-hamburg.de/en/hs.html", True),
    ("Germany", "Universität zu Köln — I. Physikalisches Institut (astro)",
     "https://astro.uni-koeln.de/jobs", True),
    ("Germany", "Ruhr-Universität Bochum — Astronomisches Institut",
     "https://www.astro.ruhr-uni-bochum.de/", True),
    ("Germany", "Max Planck Institute for Radio Astronomy (MPIfR), Bonn",
     "https://www.mpifr-bonn.mpg.de/joboffers", True),
    ("Germany", "IMPRS for Astronomy & Astrophysics Bonn/Cologne",
     "https://blog.mpifr-bonn.mpg.de/imprs/for-applicants/phd-projects/", True),
    ("Germany", "IMPRS on Astrophysics, Garching (MPA/MPE/ESO/LMU)",
     "https://www.imprs-astro.mpg.de/", True),
    ("Germany", "Leibniz Institute for Astrophysics Potsdam (AIP)",
     "https://www.aip.de/en/career/jobs/", True),
    # -- United Kingdom -------------------------------------------------------
    ("United Kingdom", "University of Cambridge — Institute of Astronomy",
     "https://www.ast.cam.ac.uk/", True),
    ("United Kingdom", "University of Oxford — Astrophysics",
     "https://www.physics.ox.ac.uk/research/subdepartment/astrophysics", True),
    ("United Kingdom", "University of Manchester — Jodrell Bank Centre",
     "https://www.jb.man.ac.uk/", True),
    ("United Kingdom", "University of Edinburgh — Institute for Astronomy (ROE)",
     "https://www.roe.ac.uk/ifa/", True),
    ("United Kingdom", "UCL — Physics & Astronomy",
     "https://www.ucl.ac.uk/physics-astronomy/", True),
    ("United Kingdom", "Imperial College London — Astrophysics",
     "https://www.imperial.ac.uk/astrophysics/", True),
    ("United Kingdom", "Durham University — Institute for Computational Cosmology",
     "https://icc.dur.ac.uk/", True),
    ("United Kingdom", "Cardiff University — Physics & Astronomy",
     "https://www.cardiff.ac.uk/physics-astronomy", True),
    ("United Kingdom", "University of Leeds — Astrophysics",
     "https://astro.leeds.ac.uk/", True),
    ("United Kingdom", "University of Portsmouth — Institute of Cosmology & Gravitation",
     "https://www.icg.port.ac.uk/", True),
    # -- France ---------------------------------------------------------------
    ("France", "Observatoire de Paris — PSL",
     "https://www.observatoiredeparis.psl.eu/", True),
    ("France", "Institut d'Astrophysique de Paris (IAP, Sorbonne/CNRS)",
     "https://www.iap.fr/", True),
    ("France", "IRAP Toulouse (Univ. Toulouse III / CNRS)",
     "https://www.irap.omp.eu/", True),
    ("France", "IPAG Grenoble (Univ. Grenoble Alpes)",
     "https://ipag.osug.fr/", True),
    ("France", "Laboratoire d'Astrophysique de Marseille (LAM)",
     "https://www.lam.fr/", True),
    ("France", "Observatoire astronomique de Strasbourg",
     "https://astro.unistra.fr/", True),
    ("France", "CRAL Lyon (Univ. Claude Bernard Lyon 1 / ENS)",
     "https://cral.univ-lyon1.fr/", True),
    ("France", "Institut d'Astrophysique Spatiale (IAS, Paris-Saclay)",
     "https://www.ias.universite-paris-saclay.fr/", True),
    ("France", "Observatoire de la Côte d'Azur (OCA, Nice)",
     "https://www.oca.eu/", True),
    ("France", "LUPM Montpellier",
     "https://www.lupm.in2p3.fr/", True),
    # -- Netherlands ----------------------------------------------------------
    ("Netherlands", "Leiden University — Leiden Observatory",
     "https://www.strw.leidenuniv.nl/", True),
    ("Netherlands", "University of Groningen — Kapteyn Astronomical Institute",
     "https://www.rug.nl/research/kapteyn/", True),
    ("Netherlands", "University of Amsterdam — Anton Pannekoek Institute",
     "https://api.uva.nl/", True),
    ("Netherlands", "Radboud University — Dept. of Astrophysics",
     "https://www.ru.nl/astrophysics/", True),
    ("Netherlands", "ASTRON — Netherlands Institute for Radio Astronomy",
     "https://www.astron.nl/vacancies/", True),
    ("Netherlands", "SRON Netherlands Institute for Space Research",
     "https://www.sron.nl/", True),
    # -- Switzerland ----------------------------------------------------------
    ("Switzerland", "ETH Zürich — Institute for Particle Physics & Astrophysics",
     "https://ipa.phys.ethz.ch/", True),
    ("Switzerland", "EPFL — Laboratory of Astrophysics (LASTRO)",
     "https://www.epfl.ch/labs/lastro/", True),
    ("Switzerland", "Université de Genève — Département d'astronomie",
     "https://www.unige.ch/sciences/astro/en/", True),
    ("Switzerland", "University of Zurich — Institute for Computational Science",
     "https://www.ics.uzh.ch/", True),
    ("Switzerland", "University of Bern — Center for Space and Habitability",
     "https://www.csh.unibe.ch/", True),
    # -- Italy ----------------------------------------------------------------
    ("Italy", "Università di Bologna — Physics & Astronomy (DIFA)",
     "https://fisica-astronomia.unibo.it/en", True),
    ("Italy", "Università di Padova — Physics & Astronomy (DFA)",
     "https://www.dfa.unipd.it/en/", True),
    ("Italy", "SISSA Trieste — Astrophysics & Cosmology",
     "https://www.sissa.it/research/astrophysics-cosmology", True),
    ("Italy", "Gran Sasso Science Institute (GSSI)",
     "https://www.gssi.it/", True),
    ("Italy", "INAF — Osservatorio di Arcetri (Firenze)",
     "https://www.arcetri.inaf.it/", True),
    ("Italy", "INAF — national jobs page",
     "https://www.inaf.it/en/", True),
    ("Italy", "Sapienza Università di Roma — Physics",
     "https://www.phys.uniroma1.it/", False),
    # -- Spain ----------------------------------------------------------------
    ("Spain", "Instituto de Astrofísica de Canarias (IAC)",
     "https://www.iac.es/en", True),
    ("Spain", "Instituto de Astrofísica de Andalucía (IAA-CSIC), Granada",
     "https://www.iaa.csic.es/en", True),
    ("Spain", "Institute of Space Sciences (ICE-CSIC), Barcelona",
     "https://www.ice.csic.es/", True),
    ("Spain", "Institut de Ciències del Cosmos, Univ. de Barcelona (ICCUB)",
     "https://icc.ub.edu/", True),
    # -- Sweden ---------------------------------------------------------------
    ("Sweden", "Stockholm University — Department of Astronomy",
     "https://www.astro.su.se/", True),
    ("Sweden", "Chalmers — Space, Earth & Environment (Onsala Observatory)",
     "https://www.chalmers.se/en/about-chalmers/work-with-us/vacancies/", False),
    ("Sweden", "Uppsala University — Physics & Astronomy",
     "https://www.physics.uu.se/", True),
    ("Sweden", "Lund University — Physics (Lund Observatory)",
     "https://www.fysik.lu.se/en/", False),
    # -- Denmark / Norway / Finland -------------------------------------------
    ("Denmark", "University of Copenhagen — Niels Bohr Institute",
     "https://nbi.ku.dk/english/", False),
    ("Denmark", "Cosmic Dawn Center (DAWN), Copenhagen",
     "https://cosmicdawn.dk/", True),
    ("Denmark", "Aarhus University — Physics & Astronomy",
     "https://phys.au.dk/en/", True),
    ("Denmark", "DTU Space",
     "https://www.space.dtu.dk/english", True),
    ("Norway", "University of Oslo — Institute of Theoretical Astrophysics",
     "https://www.mn.uio.no/astro/english/", True),
    ("Norway", "University of Bergen — Physics & Technology",
     "https://www.uib.no/en/ift", False),
    ("Finland", "University of Helsinki — Physics",
     "https://www.helsinki.fi/en/faculty-science", False),
    ("Finland", "University of Turku — Physics & Astronomy (Tuorla/FINCA)",
     "https://www.utu.fi/en/university/faculty-of-science/physics-and-astronomy", True),
    ("Finland", "Aalto University — Metsähovi Radio Observatory",
     "https://www.aalto.fi/en/metsahovi-radio-observatory", True),
    # -- Belgium / Austria / Ireland -------------------------------------------
    ("Belgium", "KU Leuven — Institute of Astronomy",
     "https://fys.kuleuven.be/ster", True),
    ("Belgium", "Ghent University — Physics & Astronomy",
     "https://www.ugent.be/we/physics-astronomy/en", True),
    ("Belgium", "Université de Liège — STAR Institute",
     "https://www.star.uliege.be/", True),
    ("Austria", "Universität Wien — Department of Astrophysics",
     "https://astro.univie.ac.at/en/", True),
    ("Austria", "Universität Innsbruck — Institute for Astro- and Particle Physics",
     "https://www.uibk.ac.at/astro/", True),
    ("Ireland", "Dublin Institute for Advanced Studies (DIAS)",
     "https://www.dias.ie/vacancies/", True),
    ("Ireland", "Trinity College Dublin — School of Physics",
     "https://www.tcd.ie/physics/", False),
    # -- Poland / Portugal / Czechia --------------------------------------------
    ("Poland", "Nicolaus Copernicus Astronomical Center (CAMK), Warsaw",
     "https://www.camk.edu.pl/en/", True),
    ("Poland", "Jagiellonian University — Astronomical Observatory, Kraków",
     "https://www.oa.uj.edu.pl/en_GB/", True),
    ("Poland", "University of Warsaw — Astronomical Observatory",
     "https://www.astrouw.edu.pl/", True),
    ("Poland", "Nicolaus Copernicus University, Toruń — Institute of Astronomy",
     "https://www.astro.umk.pl/en/", True),
    ("Portugal", "Instituto de Astrofísica e Ciências do Espaço (IA)",
     "https://www.iastro.pt/", True),
    ("Czechia", "Astronomical Institute of the Czech Academy of Sciences",
     "https://www.asu.cas.cz/en", True),
    ("Czechia", "Charles University — Astronomical Institute",
     "https://astro.mff.cuni.cz/", True),
    # -- Japan ----------------------------------------------------------------
    ("Japan", "University of Tokyo — Department of Astronomy",
     "https://www.astron.s.u-tokyo.ac.jp/en/", True),
    ("Japan", "Kyoto University — Department of Astronomy",
     "https://www.kusastro.kyoto-u.ac.jp/en/", True),
    ("Japan", "Tohoku University — Astronomical Institute",
     "http://www.astr.tohoku.ac.jp/en/", True),
    ("Japan", "Nagoya University — Physics (astrophysics labs)",
     "https://www.phys.nagoya-u.ac.jp/en/", False),
    ("Japan", "Osaka University — Physics",
     "https://www.phys.sci.osaka-u.ac.jp/en/", False),
    ("Japan", "Institute of Science Tokyo (ex-Tokyo Tech) — Physics",
     "https://www.phys.titech.ac.jp/english/", False),
    ("Japan", "Kumamoto University — Physics (cosmic magnetism / SKA group)",
     "https://www.sci.kumamoto-u.ac.jp/phys/", False),
    ("Japan", "NAOJ — National Astronomical Observatory of Japan (recruit)",
     "https://www.nao.ac.jp/en/about-naoj/recruit/", True),
    ("Japan", "SOKENDAI — Graduate Institute for Advanced Studies, Astronomy",
     "https://guas-astronomy.jp/eng/", True),
    ("Japan", "Kavli IPMU, University of Tokyo",
     "https://www.ipmu.jp/en/employment", True),
    # -- China ----------------------------------------------------------------
    ("China", "Peking University — Kavli Institute (KIAA)",
     "https://kiaa.pku.edu.cn/en", True),
    ("China", "Tsinghua University — Department of Astronomy",
     "https://astro.tsinghua.edu.cn/en/", True),
    ("China", "Nanjing University — School of Astronomy & Space Science",
     "https://astronomy.nju.edu.cn/en/", True),
    ("China", "USTC — School of Astronomy & Space Science, Hefei",
     "http://astro.ustc.edu.cn/en/", True),
    ("China", "Shanghai Jiao Tong University — Tsung-Dao Lee Institute",
     "https://tdli.sjtu.edu.cn/en/", True),
    ("China", "NAOC — National Astronomical Observatories, CAS",
     "http://english.nao.cas.cn/", True),
    ("China", "Purple Mountain Observatory (PMO), CAS",
     "http://english.pmo.cas.cn/", True),
    ("China", "Shanghai Astronomical Observatory (SHAO), CAS",
     "http://english.shao.cas.cn/", True),
    ("China", "Yunnan University — SWIFAR",
     "http://swifar.ynu.edu.cn/", True),
    ("China", "Sun Yat-sen University — Physics & Astronomy",
     "https://spa.sysu.edu.cn/en", True),
    # -- USA (Computer Science, Economics, Business, Engineering) ---
    ("United States", "Massachusetts Institute of Technology (MIT)", "https://www.mit.edu/academics/graduate", False),
    ("United States", "Stanford University — Computer Science Department", "https://cs.stanford.edu/", False),
    ("United States", "Harvard University — Department of Economics", "https://scholars.harvard.edu/economics", False),
    ("United States", "University of California, Berkeley — Computer Science", "https://cs.berkeley.edu/", False),
    ("United States", "Carnegie Mellon University — Computer Science", "https://www.cs.cmu.edu/", False),
    ("United States", "University of California, Berkeley — Economics", "https://econ.berkeley.edu/", False),
    ("United States", "Princeton University — Department of Economics", "https://economics.princeton.edu/", False),
    ("United States", "California Institute of Technology (Caltech)", "https://www.caltech.edu/", False),
    ("United States", "University of Michigan — College of Engineering", "https://www.engin.umich.edu/", False),
    ("United States", "Cornell University — College of Engineering", "https://engineering.cornell.edu/", False),
    ("United States", "Johns Hopkins University — Whiting School of Engineering", "https://engineering.jhu.edu/", False),
    ("United States", "University of Washington — Computer Science & Engineering", "https://www.cs.washington.edu/", False),
    ("United States", "Georgia Institute of Technology (Georgia Tech)", "https://www.gatech.edu/", False),

    # -- UK (Computer Science, Economics, Engineering) ---
    ("United Kingdom", "University of Cambridge — Department of Computer Science and Technology", "https://www.cl.cam.ac.uk/", False),
    ("United Kingdom", "University of Oxford — Department of Computer Science", "https://www.cs.ox.ac.uk/", False),
    ("United Kingdom", "Imperial College London — Department of Computing", "https://www.imperial.ac.uk/computing/", False),
    ("United Kingdom", "University of Oxford — Department of Economics", "https://www.economics.ox.ac.uk/", False),
    ("United Kingdom", "University of Cambridge — Department of Engineering", "https://www.eng.cam.ac.uk/", False),
    ("United Kingdom", "University of Manchester — School of Engineering", "https://www.manchester.ac.uk/engineering/", False),
    ("United Kingdom", "University of Bristol — Faculty of Engineering", "https://www.bris.ac.uk/engineering/", False),
    ("United Kingdom", "King's College London — Department of Informatics", "https://www.kcl.ac.uk/informatics/", False),

    # -- Germany (Engineering, CS, Economics) ---
    ("Germany", "Technical University of Munich (TUM) — Department of Electrical and Computer Engineering", "https://www.tum.de/en/about-tum/", False),
    ("Germany", "Technical University of Berlin (TU Berlin) — Electrical Engineering and Computer Science", "https://www.tu-berlin.de/portal/institute-organisational-units/11", False),
    ("Germany", "RWTH Aachen University — Department of Electrical Engineering and Information Technology", "https://www.eea.rwth-aachen.de/", False),
    ("Germany", "University of Stuttgart — Institute for Parallel and Distributed Systems (IPVS)", "https://www.informatik.uni-stuttgart.de/ipvs/", False),
    ("Germany", "University of Bonn — Department of Electrical Engineering, Computer Engineering and Information Technology", "https://www.ei.uni-bonn.de/", False),

    # -- France (Engineering, CS, Business) ---
    ("France", "École Polytechnique", "https://www.polytechnique.edu/", False),
    ("France", "École Normale Supérieure (ENS) — Computer Science", "https://www.sceaux.ens.fr/", False),
    ("France", "Pôle Universitaire Léonard de Vinci", "https://www.iutv.univ-paris13.fr/", False),
    ("France", "École des Ponts ParisTech", "https://www.enpc.fr/", False),

    # -- India (CS, Engineering, Economics) ---
    ("India", "Indian Institute of Technology (IIT) Delhi — Computer Science", "https://www.cse.iitd.ac.in/", False),
    ("India", "Indian Institute of Technology (IIT) Bombay — Electrical Engineering", "https://www.ee.iitb.ac.in/", False),
    ("India", "Indian Institute of Technology (IIT) Kanpur — Computer Science", "https://www.cs.iitk.ac.in/", False),
    ("India", "Indian Institute of Technology (IIT) Madras — Economics", "https://economics.iitm.ac.in/", False),
    ("India", "Indian Institute of Science (IISc) Bangalore", "https://www.iisc.ac.in/", False),

    # -- Canada (CS, Engineering, Economics) ---
    ("Canada", "University of Toronto — Department of Computer Science", "https://www.cs.toronto.edu/", False),
    ("Canada", "University of Toronto — Department of Economics", "https://www.economics.utoronto.ca/", False),
    ("Canada", "University of British Columbia — Department of Computer Science", "https://www.cs.ubc.ca/", False),
    ("Canada", "University of Waterloo — School of Computer Science", "https://uwaterloo.ca/", False),
    ("Canada", "McGill University — Department of Computer Science", "https://www.cs.mcgill.ca/", False),

    # -- Australia (CS, Engineering, Economics) ---
    ("Australia", "University of Melbourne — Department of Computing and Information Systems", "https://unimelb.edu.au/", False),
    ("Australia", "Australian National University — Research School of Computer Science", "https://cs.anu.edu.au/", False),
    ("Australia", "University of New South Wales (UNSW Sydney) — School of Computer Science and Engineering", "https://www.unsw.edu.au/", False),
    ("Australia", "University of Sydney — School of Computer Science", "https://sydney.edu.au/", False),

    # -- Switzerland (Engineering, CS) ---
    ("Switzerland", "ETH Zurich — Department of Computer Science", "https://ethz.ch/", False),
    ("Switzerland", "ETH Zurich — Department of Management, Technology and Economics", "https://www.mwt.ethz.ch/", False),

    # -- Netherlands (Engineering, CS) ---
    ("Netherlands", "Delft University of Technology", "https://www.tudelft.nl/", False),
    ("Netherlands", "Eindhoven University of Technology", "https://www.tue.nl/", False),

    # -- Singapore (Engineering, CS, Economics) ---
    ("Singapore", "National University of Singapore (NUS) — Computer Science", "https://cs.nus.edu.sg/", False),
    ("Singapore", "Nanyang Technological University (NTU) — School of Electrical and Electronic Engineering", "https://www.ntu.edu.sg/", False),
    ("Singapore", "Cornell Tech Singapore — Computer Science", "https://cornell.tech/singapore/", False),
]

# Link text that plausibly announces a doctoral opening (any language we sweep).
# A link looks like a doctoral OPENING when it carries both a PhD-ish marker
# AND an "advertisement" frame (vacancy/call/apply/deadline/position ...).
# A bare "PhD student" page (people list, qualifying-exam news, thesis defense,
# seminar schedule) must NOT qualify.
_PHD_LINK_RE = re.compile(
    r"(?=\b(ph\.?\s?d|doctoral|doctorate|studentship|doktorand\w*|dottorato|"
    r"th[eè]se|promotionsstelle\w*)\b)"
    r"\b(ph\.?\s?d|doctoral|doctorate|studentship|vacanc|open\b|"
    r"positions?|opportunit|project|fellowship|scholarship|"
    r"call|apply|application|deadline|recruit|hiring|available|join|"
    r"doktorand\w*|dottorato|th[eè]se|promotionsstelle\w*|"
    r"stellenangebot\w*|stellenausschreibung\w*|offene\s+stellen|"
    r"graduate\s+(?:program|admission)|how\s+to\s+apply)\b", re.I)

# Links that are navigation/boilerplate/events, not openings.
_PHD_LINK_BLOCK_RE = re.compile(
    r"\b(alumni|archive|news(letter)?|faq|about|contact|imprint|privacy|"
    r"login|intranet|staff|people|team|members?|employees?|exam(s|ination)?|"
    r"qualifying|defen[cs]e|seminar|colloquium|event(s)?|calendar|conference|"
    r"workshop|summer\s+school|school\s+of\s+\w+|undergraduate|bachelor|"
    r"master(?:'s|s)?\s+program|curriculum|handbook|regulations?|"
    r"bylaws|policy|equality|diversity|inclusion|wellbeing|history|"
    r"directions?|publications?|papers?|theses?|thesis\s+defen[cs]e|"
    r"graduates?\s+of|life\s+at|phd\s+life|faq)\b", re.I)


@register_source(
    "uni_departments",
    label="University department sweep",
    slow=True,
    cost_note=(
        "Visits every department page in your field's list one at a time, at "
        "the polite 2s crawl delay. Measured: 150 pages for astronomy "
        "(~5 minutes of delays alone, longer in practice over a proxy), "
        "~20 pages for most other fields. Finds openings the job boards miss, "
        "but it is by far the slowest source — leave it off for a quick "
        "search, or browse the department list yourself instead."),
)
def source_uni_departments(cfg: Config, http: Http) -> list[dict]:
    """[HTML] Sweep the department pages listed in the ACTIVE FIELD PROFILE's
    `departments:` block (top universities for YOUR major, world-wide) and
    harvest links that look like doctoral openings. Profiles without a
    `departments:` block fall back to the built-in astronomy registry
    (UNIVERSITY_DEPARTMENTS); a profile with an EMPTY list disables the
    source entirely. Plain HTML fetch only — JS-heavy career portals yield
    0 links and are noted in <output>_universities.csv, which lists every
    registry entry + fetch status for manual follow-up.
    """
    records: list[dict] = []
    seen: set = set()
    directory_rows: list[dict] = []
    wanted = ({canonical_country(c) for c in cfg.countries}
              if cfg.geo_filter_active else None)

    if cfg.departments_explicit:
        registry = [(d["country"], d["institution"], d["url"],
                     d.get("field_specific", False)) for d in cfg.departments]
    else:
        registry = list(UNIVERSITY_DEPARTMENTS)     # astronomy fallback

    if not registry:
        log.info("[uni_departments] active field profile has no departments — "
                 "skipping (add a `departments:` block to your field YAML)")
        return records

    for country, uni, url, astro in registry:
        if wanted and canonical_country(country) not in wanted:
            continue
        soup = http.get_soup(url)
        found = 0
        if soup is None:
            status = "unreachable"
        else:
            status = "ok"
            for a in soup.find_all("a", href=True):
                text = a.get_text(" ", strip=True)
                if (not text or len(text) > 220
                        or not _PHD_LINK_RE.search(text)
                        or _PHD_LINK_BLOCK_RE.search(text)):
                    continue
                link = urljoin(url, a["href"])
                key = normalize_url(link)
                if not key or key in seen or key == normalize_url(url):
                    continue
                seen.add(key)
                # astro institutes: generic titles ("open PhD positions") are
                # still astronomy openings -> give the scorer that context.
                # general physics depts: the link text must stand on its own.
                desc = (f"{text} — listed by {uni}, an astronomy/astrophysics "
                        f"institute" if astro else text)
                records.append(make_record(
                    title=text, institution=uni, country=country, url=link,
                    source="uni_departments", short_description=desc))
                found += 1
                if found >= 40:      # one page should never dominate the run
                    break
            if found == 0:
                status = "ok (0 links — page may be JS-rendered)"
        log.info("[uni_departments] %-14s %-55.55s -> %d link(s) [%s]",
                 country, uni, found, status)
        directory_rows.append({"country": country, "institution": uni,
                               "url": url, "astro_specific": astro,
                               "phd_links_found": found, "fetch_status": status})

    dir_path = cfg.stem + "_universities.csv"
    try:
        pd.DataFrame(directory_rows).to_csv(dir_path, index=False)
        log.info("[uni_departments] directory of %d departments -> %s",
                 len(directory_rows), dir_path)
    except Exception as exc:
        log.warning("[uni_departments] could not write directory: %s", exc)
    return records


# -----------------------------------------------------------------------------
# SEED URLS — hand-picked position links (+ sibling postings on the same board)
#
# Reads SEED_FILE (default ./seeds.txt; one URL per line, '#' comments), pulls
# each page through the full anti-bot fetch chain and parses it into the
# standard record schema, trying in order:
#     (1) schema.org JSON-LD "JobPosting"  (most job pages embed it; reliable)
#     (2) OpenGraph / <meta> tags
#     (3) readability-style main-text extraction (last resort)
# Hand-picked seeds bypass the relevance/type gates when SEED_BYPASS_GATE is
# on (they are still scored, classified and deadline/freshness-filtered).
# For every seed the source also tries to find the board's parent listing page
# and harvest SIBLING postings — those go through the NORMAL filters.
