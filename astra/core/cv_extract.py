"""core.cv_extract — deterministic profile extraction from CV text (Phase 3B).

WHY THIS EXISTS
---------------
``core.profile.extract_profile`` asks an LLM. With no API key configured it
returns ``None`` and the API answers "Could not extract profile from text" —
a dead end that says nothing about the cause, and the exact failure the user
reported. Worse, it makes describing your own research interests depend on a
paid third-party service.

This module extracts the same information WITHOUT any model, by matching the
CV against the vocabulary the project already ships in ``fields/*.yaml``: the
core anchors and per-subfield keywords that the relevance engine scores
against. Two consequences worth stating:

* it cannot fail wholesale — no match simply means an empty list, and the user
  edits from there;
* every term it returns is one the engine actually understands, so a picked or
  extracted keyword can never silently fail to match.

The LLM path remains available as an optional enhancement; this is the floor,
and the floor is always present.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from core.config import list_field_profiles, load_field_profile
from core.taxonomy import _compile_term
from core.utils import canonical_country

log = logging.getLogger("core.cv_extract")

# A CV shorter than this is almost certainly a paste accident.
MIN_TEXT_CHARS = 40
# Cap the per-field scan so a pathological paste cannot burn CPU.
MAX_TEXT_CHARS = 200_000

_LEVEL_PATTERNS: list[tuple[str, str]] = [
    # "Prof." is how a CV header usually says it, not "professor".
    ("professor", r"\b(full |associate |assistant )?prof(essor)?\b\.?|\btenure"),
    ("postdoc", r"\bpost-?\s?doc|\bpostdoctoral\b"),
    ("phd", r"\bph\.?\s?d\b|\bdoctoral\b|\bdphil\b|\bdoctorate\b"),
    ("masters", r"\bm\.?sc\b|\bmaster'?s?\b|\bm\.?phil\b|\bm\.?eng\b"),
    ("bachelors", r"\bb\.?sc\b|\bbachelor'?s?\b|\bb\.?eng\b|\bundergraduate\b"),
]

# Methods/tools worth recognising across every discipline. Deliberately small
# and generic — field-specific vocabulary comes from the field profiles.
_TOOL_TERMS = [
    "python", "matlab", "r language", "julia", "c++", "fortran", "java",
    "sql", "git", "linux", "bash", "latex", "excel", "spss", "stata",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy",
    "machine learning", "deep learning", "statistical analysis",
    "data analysis", "simulation", "monte carlo", "finite element",
    "spectroscopy", "microscopy", "chromatography", "mass spectrometry",
    "sequencing", "pcr", "cell culture", "fieldwork", "survey design",
]


class ExtractionResult:
    """What was found, plus WHY anything is missing.

    The brief's requirement: never a generic error. Every empty result carries
    a machine-readable ``reason`` and a sentence the UI can show verbatim.
    """

    def __init__(self) -> None:
        self.field: Optional[str] = None
        self.field_scores: dict[str, int] = {}
        self.subfields: list[str] = []
        self.keywords: list[str] = []
        self.tools: list[str] = []
        self.countries: list[str] = []
        self.experience_level: Optional[str] = None
        self.notes: list[str] = []
        self.reason: Optional[str] = None

    @property
    def found_anything(self) -> bool:
        return bool(self.field or self.keywords or self.tools
                    or self.countries or self.experience_level)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "field_scores": self.field_scores,
            "subfields": self.subfields,
            "keywords": self.keywords,
            "tools": self.tools,
            "countries": self.countries,
            "experience_level": self.experience_level,
            "found_anything": self.found_anything,
            "notes": self.notes,
            "reason": self.reason,
        }


def _matches(text: str, terms: list[str]) -> list[str]:
    """Terms from ``terms`` that appear in ``text``, using the SAME matching
    rules as the relevance engine (prefix match, ALL-CAPS acronyms are
    case-sensitive whole words)."""
    hits: list[str] = []
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            continue
        try:
            if _compile_term(term).search(text):
                hits.append(term)
        except re.error:      # a malformed profile term must never crash this
            continue
    return hits


def extract_from_text(raw_text: str,
                      field_hint: Optional[str] = None) -> ExtractionResult:
    """Extract field, subfields, keywords, tools, countries and career level.

    Never raises and never returns None. When nothing is recognised the result
    says which of the possible causes applies, so the UI can explain itself.
    """
    result = ExtractionResult()
    text = (raw_text or "").strip()

    if not text:
        result.reason = "empty_text"
        result.notes.append("No text was provided.")
        return result
    if len(text) < MIN_TEXT_CHARS:
        result.reason = "too_short"
        result.notes.append(
            f"Only {len(text)} characters of text — too little to recognise "
            "anything. Paste more of your CV, or pick your keywords by hand.")
        return result
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        result.notes.append("Very long text — only the first part was scanned.")

    # --- which field does this CV look like? ---------------------------------
    # Score every shipped profile by how many of its core anchors appear. The
    # winner is a suggestion, not a verdict: the user can always override.
    candidates = [field_hint] if field_hint else list_field_profiles()
    best_profile = None
    for name in candidates:
        profile = load_field_profile(name)
        if not profile:
            continue
        anchors = [a for a in (profile.get("core_anchors") or [])
                   if isinstance(a, str)]
        hits = _matches(text, anchors)
        if hits:
            result.field_scores[name] = len(hits)
        if best_profile is None or len(hits) > result.field_scores.get(
                best_profile[0], 0):
            if hits or best_profile is None:
                best_profile = (name, profile, hits)

    if result.field_scores:
        result.field = max(result.field_scores, key=result.field_scores.get)
        best_profile = (result.field, load_field_profile(result.field), [])
    elif field_hint:
        result.field = field_hint
        best_profile = (field_hint, load_field_profile(field_hint), [])
    else:
        result.reason = "no_field_match"
        result.notes.append(
            "No research field could be recognised from this text. Choose "
            "your field and pick keywords directly — that works just as well.")

    # --- subfields + keywords from the winning profile ------------------------
    if best_profile and best_profile[1]:
        profile = best_profile[1]
        anchor_hits = _matches(text, [a for a in
                                      (profile.get("core_anchors") or [])
                                      if isinstance(a, str)])
        keyword_hits: list[str] = []
        subfields = profile.get("subfields")
        if isinstance(subfields, dict):
            for sid, entry in subfields.items():
                if not isinstance(entry, dict):
                    continue
                kws = [k for k in (entry.get("keywords") or [])
                       if isinstance(k, str)]
                hits = _matches(text, kws)
                if hits:
                    result.subfields.append(str(sid))
                    keyword_hits.extend(hits)
        # Anchors first (strongest signal), then subfield keywords.
        result.keywords = list(dict.fromkeys([*anchor_hits, *keyword_hits]))

    # --- discipline-neutral extras -------------------------------------------
    result.tools = _matches(text, _TOOL_TERMS)

    for level, pattern in _LEVEL_PATTERNS:
        if re.search(pattern, text, re.I):
            result.experience_level = level
            break

    result.countries = _countries_in(text)

    if not result.found_anything and result.reason is None:
        result.reason = "nothing_recognised"
        result.notes.append(
            "Nothing recognisable was found in this text. Pick your field and "
            "keywords by hand — it is quicker and more accurate anyway.")
    return result


def _countries_in(text: str) -> list[str]:
    """Canonical country names mentioned in the text.

    Only checks capitalised words/phrases, so 'us' inside a sentence or
    'turkey' in a recipe cannot masquerade as a country.
    """
    found: list[str] = []
    for token in re.findall(r"\b[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2}", text):
        canon = canonical_country(token)
        if canon and canon not in found:
            found.append(canon)
    return found
