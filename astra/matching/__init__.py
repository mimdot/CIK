"""matching — deterministic profile↔opportunity scoring (Sprint 03, Track B).

Pure-Python scoring of job opportunities against the extracted UserProfile:
topic / method / location dimensions + a template explainer. The monolith
re-exports these names for back-compat; pipeline/run.py uses score_match to
stamp match_score + match_explanation on every kept record when a profile is
active (Track C3).
"""

from matching.scorer import (  # noqa: F401
    LOCATION_WEIGHT,
    METHOD_WEIGHT,
    NEUTRAL,
    TOPIC_WEIGHT,
    MatchResult,
    _build_mini_cfg,
    _profile_core_terms,
    explain_match,
    location_score,
    method_score,
    missing_methods,
    next_actions,
    score_many,
    score_match,
    topic_score,
)

__all__ = [
    "LOCATION_WEIGHT", "METHOD_WEIGHT", "NEUTRAL", "TOPIC_WEIGHT",
    "MatchResult", "_build_mini_cfg", "_profile_core_terms", "explain_match",
    "location_score", "method_score", "missing_methods", "next_actions",
    "score_many", "score_match", "topic_score",
]
