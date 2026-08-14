"""core.taxonomy — relevance scoring + position-type and geo classification.

Extracted verbatim from phd_aggregator.py (migration Step 3). Pure relocation:
no behavior, signature, or output changes. Also re-homes ``_compile_term`` /
``compile_taxonomy`` (originally placed in core.config during Step 1).

The ``Config`` type is imported type-only to keep the dependency acyclic:
core.config imports these two compile functions back, so a runtime import here
would form a cycle. ``canonical_country`` is pulled from core.utils (which in
turn reads the live ``_ALIAS_LOOKUP`` from core.config).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from core import position_types
from core.utils import canonical_country

if TYPE_CHECKING:
    from core.config import Config


def _compile_term(term: str) -> re.Pattern:
    """Compile one taxonomy term.

    ALL-CAPS short terms  -> case-SENSITIVE whole-word (\"ISM\" not \"mechanism\",
                             \"ALMA\" not \"alma mater\").
    everything else       -> case-insensitive prefix match, with spaces/hyphens
                             interchangeable (\"gamma-ray burst\" == \"gamma ray
                             burst\", \"astrophysic\" catches \"astrophysics\").
    """
    if term.isupper() and len(term) <= 6:
        return re.compile(r"\b" + re.escape(term) + r"\b")
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip()) if p]
    return re.compile(r"\b" + r"[\s\-]+".join(parts), re.I)


def compile_taxonomy(cfg: "Config") -> None:
    cfg._core_rx = [(t, _compile_term(t)) for t in cfg.core_anchors]
    cfg._context_rx = [(t, _compile_term(t)) for t in cfg.context_terms]
    cfg._negative_rx = [(t, _compile_term(t)) for t in cfg.negative_terms]


def score_relevance(title: str, desc: str, cfg: "Config"
                    ) -> tuple[float, list[str], list[str], list[str]]:
    """Score a post against the taxonomy.

    Returns (score, core_anchors_matched, context_matched, negatives_matched).
    Only title + description are scored — institution/department names are NOT
    (a diode-laser PhD in a \"Dept of Physics & Astronomy\" must not qualify).
    """
    title = title or ""
    desc = desc or ""
    w = cfg.weights

    core_t = [t for t, rx in cfg._core_rx if rx.search(title)]
    core_d = [t for t, rx in cfg._core_rx
              if t not in core_t and rx.search(desc)]
    ctx_t = [t for t, rx in cfg._context_rx if rx.search(title)]
    ctx_d = [t for t, rx in cfg._context_rx
             if t not in ctx_t and rx.search(desc)]
    both = title + " \n " + desc
    negs = [t for t, rx in cfg._negative_rx if rx.search(both)]

    score = (w["core_title"] * len(core_t) + w["core_desc"] * len(core_d)
             + w["context_title"] * len(ctx_t) + w["context_desc"] * len(ctx_d))
    # A core anchor in the TITLE overrides negatives (genuine crossovers, e.g.
    # \"quantum sensors for gravitational-wave detection\").
    if not core_t and negs:
        score += w["negative"] * len(negs)
    return score, core_t + core_d, ctx_t + ctx_d, negs


def is_relevant(score: float, anchors: list[str], cfg: "Config",
                title_anchors: Optional[list[str]] = None) -> bool:
    """True if a post clears the relevance gate: at least one core anchor and
    score >= threshold. With cfg.require_title_anchor set, at least one core
    anchor must ALSO match the TITLE — description-only matches boost the score
    but can never qualify the post alone."""
    if cfg.require_title_anchor and not title_anchors:
        return False
    return bool(anchors) and score >= cfg.threshold


# -----------------------------------------------------------------------------
# Position-type classifier (hardened PhD gate)
# -----------------------------------------------------------------------------
# BACK-COMPAT SHIMS. The registry now lives in core.position_types, backed by
# position_types.yaml — that is where patterns are edited. These names are
# DERIVED from it so external importers (and the phd_aggregator.py re-export
# shim) keep working; assigning to them has no effect on classification.
_TYPE_PATTERNS: dict[str, list[str]] = {
    entry.name: list(entry.patterns) for entry in position_types.TYPES
}
_TYPE_REGEX = {entry.name: list(entry._rx) for entry in position_types.TYPES}
_TYPE_PRIORITY = [entry.name for entry in position_types.TYPES]

# Phrases that mention a level as a REQUIREMENT rather than the thing on offer
# ("must hold a PhD" in a postdoc ad). Now per-type in the registry; this union
# is kept for back-compat.
_PHD_REQUIREMENT_NOISE = re.compile(
    "|".join(n for entry in position_types.TYPES
             for n in entry.requirement_noise) or r"(?!x)x",
    re.I)


def _match_type(text: str) -> Optional[str]:
    """First type whose patterns hit, in registry order (= priority)."""
    if not text:
        return None
    for entry in position_types.TYPES:
        if entry.matches(text):
            return entry.name
    return None


def classify_position_type(title: Optional[str], description: Optional[str]) -> str:
    """Return a position-type name (phd/postdoc/…) or 'unknown'.

    Title wins; otherwise the description decides, with each type's
    "mentioned as a requirement" phrases stripped first ("must hold a PhD" in
    a postdoc ad must not make it a PhD opening). Types come from
    :mod:`core.position_types` — a YAML registry, so adding Master's or
    Scholarship needs no change here.
    """
    by_title = _match_type(title or "")
    if by_title:
        return by_title
    desc = description or ""
    for entry in position_types.TYPES:
        desc = entry.strip_requirement_noise(desc)
    return _match_type(desc) or position_types.UNKNOWN


def country_allowed(canon: Optional[str], cfg: "Config") -> tuple[bool, bool]:
    """Return (keep, is_unknown_kept_and_flagged) under the region filter."""
    if not cfg.geo_filter_active:
        return True, False
    wanted = {canonical_country(c) or c for c in cfg.countries}
    if canon is None:
        return cfg.keep_ambiguous, cfg.keep_ambiguous
    return canon in wanted, False