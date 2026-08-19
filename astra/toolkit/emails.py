"""toolkit.emails — the applicant profile + per-position application emails
(migration Step 10). Extracted verbatim from astra.py.

PERSONAL DATA LIVES IN applicant.yaml (gitignored — copy
applicant.example.yaml and fill it in). The placeholders are what a fresh
clone sees; --write-emails warns until a real profile is provided.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from core.config import Config, _find_config_path, _load_yaml_file
from core.utils import _slugify

log = logging.getLogger("astra")

APPLICANT_PROFILE = {
    "name": "Your Name",
    "email": "you@example.org",
    "alt_email": "",
    "phone": "",
    "cv_filename": "CV.pdf",
    "msc": "M.Sc. in <your subject>, <your university> (<years>)",
    "bsc": "B.Sc. in <your subject>, <your university> (<years>)",
    "publication": "<your representative publication, full citation>",
    "references": "<referee name (affiliation, email)> — with their consent",
}


def _ensure_applicant_profile() -> None:
    """Overlay applicant.yaml (CWD or script dir; gitignored) onto the
    placeholder profile above. Missing file -> placeholders stay."""
    path = _find_config_path("applicant.yaml")
    if not path:
        return
    data = _load_yaml_file(path)
    if isinstance(data, dict):
        for key in APPLICANT_PROFILE:
            if data.get(key):
                APPLICANT_PROFILE[key] = str(data[key])


_ensure_applicant_profile()

# Tailoring rules: first regex hit against title+institution+description adds
# its sentence to the email's fit paragraph (max 3, in this priority order).
_EMAIL_FIT_RULES: list[tuple[str, str]] = [
    (r"magneti|faraday|polari[sz]|dynamo|\bMHD\b|rotation measure|synchrotron",
     "I am currently mapping magnetic fields in molecular clouds through "
     "Faraday rotation and Faraday tomography, working with Dr. Mehrnoosh "
     "Tahani (University of South Carolina) within the international GMIMS "
     "collaboration — experience that maps directly onto the science of this "
     "position."),
    (r"cosmic.?ray|radio (?:astronom|continuum|interferomet)|\bLOFAR\b|\bSKA\b"
     r"|\bVLA\b|low.?frequency",
     "In my IC 342 study I separated thermal from non-thermal radio emission "
     "with wavelet methods to trace cosmic-ray propagation lengths — directly "
     "relevant to the radio-continuum and cosmic-ray focus of this project."),
    (r"interstellar|\bISM\b|molecular cloud|star.?form|dust|nebula|filament",
     "The physics of the interstellar medium is the core of my research "
     "profile: molecular-cloud magnetic fields, dust properties, and the "
     "coupling between star formation and non-thermal processes, combined "
     "across radio, infrared and optical tracers."),
    (r"galax|extragalactic|milky way",
     "Through my resolved study of IC 342 and the NEARBY GALAXIES "
     "collaboration I have hands-on experience linking radio continuum, "
     "magnetic fields and star formation in nearby galaxies."),
    (r"survey|machine.?learning|big data|statisti|pipeline|data.?(analysis|scien)",
     "I routinely analyse large survey datasets — LOFAR LoTSS, GMIMS, CHIME, "
     "VLA, Planck polarization, Spitzer/Herschel/WISE and GALEX — in a Python "
     "(NumPy/AstroPy) stack alongside AIPS and DS9."),
    (r"cosmolog|\bCMB\b|gravitat|dark (?:matter|energy)",
     "My M.Sc. in Gravity & Cosmology (Kharazmi University) gives me the "
     "theoretical grounding in gravitation and cosmology that complements my "
     "observational work."),
    (r"instrument|detector|receiver|antenna|telescope construction",
     "During my B.Sc. I designed and built small VLF-band radio detectors and "
     "reduced GMRT data, giving me end-to-end familiarity with radio "
     "instrumentation."),
]
_EMAIL_FIT_FALLBACK = (
    "My background combines multi-wavelength observations (radio, infrared, "
    "optical) with the study of magnetic fields and cosmic-ray propagation in "
    "galaxies — from molecular clouds to nearby spiral disks.")


def build_email(record: dict) -> tuple[str, str]:
    """Return (subject, body) customized for one position record."""
    p = APPLICANT_PROFILE
    title = record.get("title") or "the advertised PhD position"
    inst = record.get("institution")
    hay = " ".join(filter(None, [record.get("title"),
                                 record.get("institution"),
                                 record.get("short_description")]))
    fits = [s for rx, s in _EMAIL_FIT_RULES if re.search(rx, hay, re.I)][:3]
    if not fits:
        fits = [_EMAIL_FIT_FALLBACK]

    subject = f'PhD application — "{title}"' + (f" ({inst})" if inst else "")
    deadline = record.get("deadline")
    deadline_note = (f" I understand applications close on {deadline}." if deadline else "")

    src = (record.get("source") or "").split(";")[0].strip()
    src_names = {"euraxess": "EURAXESS", "nature_careers": "Nature Careers",
                 "jobs_ac_uk": "jobs.ac.uk", "findaphd": "FindAPhD",
                 "academictransfer": "AcademicTransfer", "aas": "the AAS Job Register",
                 "academicjobsonline": "AcademicJobsOnline", "jrecin": "JREC-IN",
                 "eso": "the ESO recruitment portal", "esa": "the ESA careers portal",
                 "linkedin": "LinkedIn",
                 "uni_departments": "your institute's website"}
    via = src_names.get(src, "your job listing")

    body = f"""Dear members of the selection committee,

I am writing to apply for the PhD position "{title}"{f' at {inst}' if inst else ''}, which I found through {via}.{deadline_note} The project is an excellent match for my research profile, and I would be glad to contribute to it.

I hold an {p['msc']} and a {p['bsc']}. From 2020 to 2023 I was a research assistant at the School of Astronomy, Institute for Research in Fundamental Sciences (IPM), Tehran, supervised by Prof. Fatemeh S. Tabatabaei. My master's research on the radio–IR correlation in the nearby galaxy IC 342, based on LOFAR LoTSS data and carried out within the LOFAR Magnetism Key Science Project, led to a first-author paper in Astronomy & Astrophysics ({p['publication']}).

{' '.join(fits)}

My CV ({p['cv_filename']}) is attached with full details of my publications, talks, and observational data experience. {p['references']} would be glad to provide references. I would welcome the opportunity to discuss the project in an online interview at your convenience.

Thank you for your time and consideration.

Sincerely,
{p['name']}
Email: {p['email']} / {p['alt_email']}
Phone: {p['phone']}
"""
    return subject, body


def write_emails(records: list[dict], cfg: Config) -> None:
    """One customized application email per kept position -> emails/ dir."""
    import pandas as pd  # local import: only needed for CSV writing

    if not records:
        log.warning("[emails] no positions to write emails for — run the "
                    "aggregation first (or drop --no-fetch).")
        return
    if APPLICANT_PROFILE["email"] == "you@example.org":
        log.warning("[emails] no applicant.yaml found — emails will carry "
                    "PLACEHOLDER contact details (copy applicant.example.yaml "
                    "to applicant.yaml and fill it in)")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(cfg.stem)), "emails")
    os.makedirs(out_dir, exist_ok=True)
    index = []
    for i, r in enumerate(records, 1):
        subject, body = build_email(r)
        fname = f"{i:03d}_{_slugify(r.get('institution'))}_{_slugify(r.get('title'), 40)}.txt"
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"To:      (find the contact address in the ad)\n"
                     f"Subject: {subject}\n"
                     f"Ad URL:  {r.get('url') or '-'}\n"
                     f"{'-' * 72}\n{body}")
        index.append({"file": fname, "title": r.get("title"),
                      "institution": r.get("institution"),
                      "country": r.get("country"), "deadline": r.get("deadline"),
                      "url": r.get("url")})
    pd.DataFrame(index).to_csv(os.path.join(out_dir, "_index.csv"), index=False)
    log.info("[emails] wrote %d customized emails -> %s (attach %s before "
             "sending; ALWAYS read each one and fill in the recipient)",
             len(index), out_dir, APPLICANT_PROFILE["cv_filename"])
