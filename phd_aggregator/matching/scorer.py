"""matching — deterministic profile↔opportunity scoring (Sprint 03, Track B).

Pure Python, no LLM, no network: a candidate opportunity is scored against the
extracted :class:`UserProfile` on three dimensions (topic / method / location),
each normalized to 0-1, then blended into an overall score with a fixed
weighting. A template-based explainer turns the scores into a human-readable
"why this match, what's missing" paragraph.

Design notes:
- ``topic_score`` reuses :func:`core.taxonomy.score_relevance` the opposite way
  around: instead of scoring a post against the default field taxonomy, it
  builds a *mini taxonomy from the profile's domain/subfield* and scores the
  post against that, so a profile in any field works unchanged.
- Neutral score 0.5 is returned when there is nothing to judge against (profile
  has no methods/tools, or the opportunity carries no country), so missing
  information never inflates or tanks a match.
- Everything is deterministic and unit-testable with a plain ``UserProfile`` +
  ``make_record`` fixtures.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Optional

from core.config import Config, _compile_term, compile_taxonomy
from core.profile_schema import UserProfile
from core.taxonomy import score_relevance
from core.utils import canonical_country

# Blend weights (topic / method / location). Kept module-level so tests can
# verify the mix and golden scores are stable.
TOPIC_WEIGHT = 0.5
METHOD_WEIGHT = 0.3
LOCATION_WEIGHT = 0.2
NEUTRAL = 0.5  # returned when there is nothing to compare against

# Two title anchors = a perfect score (the strongest signal the mini taxonomy
# can produce), so topic_score normalizes by that ceiling.
TOPIC_NORMALIZATION_FACTOR = 2

# Cache of compiled mini-taxonomy Configs, keyed on the profile terms that
# drive them plus the caller's scoring weights (so per-call cfg overrides still
# win without a wholesale cache clear — the batch path reuses one compiled mini
# taxonomy across every opportunity, turning the digest sweep into O(P) instead
# of O(P x M)).
_mini_cfg_cache: dict[tuple, Config] = {}


def _weights_fingerprint(cfg: Config) -> tuple:
    """Order-insensitive fingerprint of the scoring weights that feed the mini
    taxonomy, so two configs with different weights never share a cache entry."""
    return tuple(sorted((k, round(float(v), 6)) for k, v in cfg.weights.items()))


@dataclass
class MatchResult:
    """Result of scoring one opportunity against a profile."""

    overall_score: float
    topic_score: float
    method_score: float
    location_score: float
    explanation: str
    confidence: float
    percentile: Optional[float] = None
    suggestions: tuple = ()


def _profile_core_terms(profile: UserProfile) -> list[str]:
    """Derive core anchor terms from the profile's domain + subfield.

    The domain and subfield are free text ("interstellar medium",
    "cosmic magnetism"), so we split them into words and keep the meaningful
    ones; ``_compile_term`` turns each into a case-insensitive prefix regex
    (matching the main taxonomy's behavior), so "molecul" catches
    "molecular" etc."""
    raw = " ".join(t for t in (profile.domain, profile.subfield) if t)
    words = [w for w in re.split(r"[^\w\-]+", raw.lower()) if w and len(w) > 1]
    return words or ([profile.domain.lower()] if profile.domain else [])


def _build_mini_cfg(profile: UserProfile, cfg: Config) -> Config:
    """A copy of the runtime Config whose taxonomy is replaced by the
    profile's own terms — this is what lets score_relevance score in ANY field.
    Profile skills/methods/tools become context terms (they boost, never
    qualify alone); constraints are ignored for topics (they are location).

    Compiled once per distinct profile content + weights and cached; the key
    includes a fingerprint of ``cfg.weights`` so per-call config overrides can
    never receive a mini taxonomy compiled against different weights."""
    key = (profile.domain, profile.subfield,
           tuple(profile.methods), tuple(profile.tools),
           _weights_fingerprint(cfg))
    cached = _mini_cfg_cache.get(key)
    if cached is not None:
        return cached
    mini = copy.copy(cfg)
    mini.weights = dict(cfg.weights)
    mini.core_anchors = _profile_core_terms(profile)
    mini.context_terms = [str(t).lower() for t in
                          (profile.skills + profile.methods + profile.tools)
                          if str(t)]
    mini.negative_terms = []
    compile_taxonomy(mini)
    _mini_cfg_cache[key] = mini
    return mini


def topic_score(profile: UserProfile, opportunity: dict,
                cfg: Config,
                mini_cfg: Optional[Config] = None) -> float:
    """0-1: how well the opportunity's title+description match the profile's
    domain/subfield. Built on score_relevance with a mini taxonomy.

    ``mini_cfg`` may be precompiled via :func:`_build_mini_cfg` (batch callers
    reuse it across opportunities instead of recompiling per record).

    Normalization: one core anchor in the TITLE (weight core_title, 5.0 in the
    default taxonomy) maps to 0.5, two anchors to 1.0, a description-only
    anchor (core_desc, 2.5) to ~0.25 — a defensible, smooth gradient."""
    hay = " ".join(t for t in (opportunity.get("title"),
                               opportunity.get("short_description")) if t)
    if not hay.strip():
        return 0.0
    if mini_cfg is None:
        mini_cfg = _build_mini_cfg(profile, cfg)
    score, _, _, _ = score_relevance(opportunity.get("title") or "",
                                     opportunity.get("short_description") or "",
                                     mini_cfg)
    return max(0.0, min(1.0, score / max(1.0, (cfg.weights.get("core_title", 5.0)
                                               * TOPIC_NORMALIZATION_FACTOR))))


def _compile_methods(profile: UserProfile) -> list[tuple[str, object]]:
    """(term, compiled-regex) pairs for the profile's methods + tools, so the
    regexes are compiled once per profile instead of on every call."""
    terms = [str(t) for t in (profile.methods + profile.tools) if str(t)]
    return [(t, _compile_term(t)) for t in terms]


def method_score(profile: UserProfile, opportunity: dict,
                 method_regex: Optional[list[tuple[str, object]]] = None) -> float:
    """0-1: overlap between the profile's methods+tools and the opportunity
    text (Jaccard-like: matched terms / profile terms). Empty profile methods
    + tools -> 0.5 (neutral). ``method_regex`` may be precompiled via
    ``_compile_methods`` to avoid recompiling on every call."""
    terms = [str(t) for t in (profile.methods + profile.tools) if str(t)]
    if not terms:
        return NEUTRAL
    hay = " ".join(t for t in (opportunity.get("title"),
                               opportunity.get("short_description"),
                               opportunity.get("institution")) if t)
    rx = method_regex if method_regex is not None else _compile_methods(profile)
    matched = [t for t, r in rx if r.search(hay)]
    return len(matched) / len(terms)


def location_score(profile: UserProfile, opportunity: dict) -> float:
    """0-1: does the opportunity's country match the profile's preferences?
    - 1.0 if the country is in profile.countries_preferred
    - 0.0 if the country is blocked by a constraint (anti-preference)
    - 0.5 if the profile expresses no preference, or the post has no country
    - 0.25 otherwise (country known but not preferred)"""
    country = canonical_country(opportunity.get("country"))
    if not country:
        return NEUTRAL
    if not profile.countries_preferred:
        return NEUTRAL
    prefs = {canonical_country(c) or c for c in profile.countries_preferred}
    blocked = {c for c in (canonical_country(c) for c in profile.constraints) if c}
    if country in blocked:
        return 0.0
    if country in prefs:
        return 1.0
    return 0.25


def missing_methods(profile: UserProfile, opportunity: dict,
                    method_regex: Optional[list[tuple[str, object]]] = None
                    ) -> list[str]:
    """Profile methods/tools NOT mentioned in the opportunity text.

    Used for the "Consider learning: …" suggestions (the API layer decides how
    many to surface). ``method_regex`` may be precompiled via
    ``_compile_methods`` to avoid recompiling on every call."""
    methods = [str(m) for m in (profile.methods + profile.tools) if str(m)]
    if not methods:
        return []
    hay = " ".join(t for t in (opportunity.get("title"),
                               opportunity.get("short_description"),
                               opportunity.get("institution")) if t)
    rx = method_regex if method_regex is not None else _compile_methods(profile)
    return [m for m, r in rx if not r.search(hay)]


def _fmt_deadline(value) -> str:
    """A short display string for a deadline (datetime or ISO-ish string)."""
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")
    return str(value)


def next_actions(profile: UserProfile, opportunity: dict) -> list[str]:
    """Deterministic 'what to do next' actions for one match (Sprint 09, A4).

    Pure function of the profile + opportunity facts — no LLM, no network.
    Builds a short actionable list: apply-by deadline, funding note, the top
    missing methods to strengthen, and a relocation note when the posting's
    country is not among the profile's preferences. Falls back to a generic
    action when nothing specific applies.
    """
    actions: list[str] = []
    deadline = _fmt_deadline(opportunity.get("deadline"))
    if deadline:
        actions.append(f"Apply by {deadline}")

    funding = (opportunity.get("funding_status")
               or opportunity.get("funding_requirement") or "").strip()
    if funding and "funded" in funding.lower():
        actions.append("Funding: fully funded")
    elif funding:
        actions.append("Check funding details")

    # 'Missing methods' is only meaningful when the posting carries some text
    # (an empty posting would "miss" every method — pure noise).
    hay = " ".join(t for t in (opportunity.get("title"),
                               opportunity.get("short_description"),
                               opportunity.get("institution")) if t)
    if hay.strip():
        missing = sorted(set(missing_methods(profile, opportunity)))[:3]
        if missing:
            actions.append("Strengthen: " + ", ".join(missing))

    country = canonical_country(opportunity.get("country"))
    if country and profile.countries_preferred:
        prefs = {canonical_country(c) or c for c in profile.countries_preferred}
        if country not in prefs:
            actions.append(f"Requires relocation to {country}")

    if not actions:
        actions.append("Review the posting and prepare your application")
    return actions


def explain_match(profile: UserProfile, opportunity: dict,
                  scores: dict,
                  method_regex: Optional[list[tuple[str, object]]] = None,
                  percentile: Optional[float] = None,
                  suggestions: Optional[list[str]] = None) -> str:
    """Template-based explanation of why this opportunity matches (or not),
    plus what is missing. Scores dict keys: topic_score/method_score/
    location_score. ``method_regex`` may be precompiled via ``_compile_methods``
    to avoid recompiling on every call.

    Optional ``percentile`` (0-100) appends a comparative line ("more relevant
    than X% of opportunities"); ``suggestions`` appends "Consider learning: …".
    Both are computed by the caller that knows the full score distribution."""
    domain = profile.domain or "this field"
    subfield = profile.subfield
    subject = f"{domain}/{subfield}" if subfield else domain

    parts: list[str] = []
    t = scores.get("topic_score", 0.0)
    if t > 0.7:
        parts.append(f"Strong topic match: your {subject} aligns directly with "
                     "this position.")
    elif t > 0.4:
        parts.append(f"Partial topic match: related to your {domain} "
                     "background.")
    else:
        parts.append("Weak topic match: this position is outside your primary "
                     "field.")

    methods = [str(m) for m in (profile.methods + profile.tools) if str(m)]
    if methods:
        hay = " ".join(t for t in (opportunity.get("title"),
                                   opportunity.get("short_description"),
                                   opportunity.get("institution")) if t)
        rx = method_regex if method_regex is not None else _compile_methods(profile)
        matched = [m for m, r in rx if r.search(hay)]
        missing = [m for m, r in rx if not r.search(hay)]
        if matched:
            parts.append(f"Methods/tools you can bring: "
                         f"{', '.join(sorted(set(matched)))}.")
        missing_display = sorted(set(missing))[:5]
        if missing_display:
            suffix = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
            parts.append(f"Missing (advertised elsewhere): "
                         f"{', '.join(missing_display)}{suffix}.")
        if not matched:
            parts.append("None of your listed methods/tools are mentioned in "
                         "the posting.")
    else:
        parts.append("Your profile lists no methods/tools to compare against.")

    loc = scores.get("location_score", 0.0)
    country = canonical_country(opportunity.get("country"))
    if loc >= 1.0:
        parts.append(f"Location is a preferred one ({country}).")
    elif loc == 0.0:
        parts.append(f"Location ({country or 'unspecified'}) conflicts with "
                     "your constraints.")
    elif loc >= NEUTRAL:
        parts.append("Location is acceptable (no strong preference either "
                     "way).")
    else:
        parts.append(f"Location ({country or 'unspecified'}) is not on your "
                     "preferred list.")

    if suggestions:
        parts.append(f"Consider learning: {', '.join(suggestions)}.")
    if percentile is not None:
        parts.append(f"This position is more relevant than {percentile:.0f}% "
                     "of opportunities.")

    return " ".join(parts)


def _score_match_with(profile: UserProfile, opportunity: dict, cfg: Config,
                      mini_cfg: Config, method_regex,
                      percentile: Optional[float] = None,
                      suggestions: Optional[list[str]] = None) -> MatchResult:
    """Shared scoring body with precompiled mini-cfg + method regexes.

    ``score_match`` compiles on demand; batch callers (digest sweep,
    preview) pass the precompiled artifacts via :func:`score_many` so the
    regexes and mini taxonomy are built once per profile, not once per
    opportunity."""
    t = topic_score(profile, opportunity, cfg, mini_cfg=mini_cfg)
    m = method_score(profile, opportunity, method_regex)
    loc = location_score(profile, opportunity)
    overall = (TOPIC_WEIGHT * t + METHOD_WEIGHT * m + LOCATION_WEIGHT * loc)
    overall = round(max(0.0, min(1.0, overall)), 3)
    explanation = explain_match(profile, opportunity,
                                {"topic_score": t, "method_score": m,
                                 "location_score": loc}, method_regex,
                                percentile=percentile,
                                suggestions=suggestions)
    return MatchResult(overall_score=overall, topic_score=round(t, 3),
                       method_score=round(m, 3), location_score=round(loc, 3),
                       explanation=explanation,
                       confidence=profile.confidence,
                       percentile=percentile,
                       suggestions=tuple(suggestions) if suggestions else ())


def score_match(profile: UserProfile, opportunity: dict,
                cfg: Config, percentile: Optional[float] = None,
                suggestions: Optional[list[str]] = None) -> MatchResult:
    """Score one opportunity against a profile. Deterministic, no LLM.

    The opportunity dict is any normalized record (make_record output): title,
    short_description, institution, country. Returns a MatchResult with the
    three dimension scores, the blended overall score, and an explanation.

    Optional ``percentile`` / ``suggestions`` are passed straight through to
    the explainer (see :func:`explain_match`) — the caller supplies them when
    it knows the full score distribution."""
    mini_cfg = _build_mini_cfg(profile, cfg)
    method_regex = _compile_methods(profile)
    return _score_match_with(profile, opportunity, cfg, mini_cfg, method_regex,
                             percentile=percentile, suggestions=suggestions)


def score_many(profile: UserProfile, opportunities: list[dict], cfg: Config,
               percentile: Optional[float] = None) -> list[MatchResult]:
    """Score many opportunities against one profile (O(P), not O(P x M)).

    Compiles the mini taxonomy and the method/tool regexes ONCE per profile and
    reuses them for every opportunity — the batch entrypoint the digest sweep
    and email preview use instead of calling :func:`score_match` per record
    (which used to rebuild both for each opportunity). Returns one MatchResult
    per input dict, in order.
    """
    mini_cfg = _build_mini_cfg(profile, cfg)
    method_regex = _compile_methods(profile)
    return [
        _score_match_with(profile, opp, cfg, mini_cfg, method_regex,
                          percentile=percentile)
        for opp in opportunities
    ]
