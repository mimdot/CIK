"""api.routes.matches — profile↔opportunity matches with explainability
(Sprint 04, A3). Matches are computed with the deterministic
:func:`matching.scorer.score_match` engine (no LLM, no network), sorted by
score, and each item carries the explainability text. Feedback on a match is
stored via the ``match_feedback`` table.

The scored list is deterministic for a given profile, so it is cached per
profile in a module-level dict and paginated in memory. The cache is
invalidated by bumping ``CACHE_VERSION`` (see :func:`invalidate_match_cache`),
which the profile build/update endpoints call whenever the active profile
changes.
"""

from __future__ import annotations

import argparse
import threading
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_active_profile_row, get_current_user, get_db
from api.schemas import MatchFeedbackRequest
from api.serializers import opportunity_out
from core import cache
from core.config import build_config, field_profile_keywords
from core.profile_schema import UserProfile
from db.models import Opportunity
from db.repositories import MatchFeedbackRepo
from matching import missing_methods, next_actions, score_match

router = APIRouter(prefix="/api/matches", tags=["matches"])

# (CACHE_VERSION, profile_id) -> full sorted scored list (deterministic).
_match_cache: dict[tuple[int, int], list[dict]] = {}
_match_cache_lock = threading.Lock()
CACHE_VERSION = 0


def invalidate_match_cache() -> None:
    """Bump the cache version so :func:`list_matches` recomputes on next call."""
    global CACHE_VERSION
    CACHE_VERSION += 1


@lru_cache(maxsize=1)
def _default_cfg():
    """A default Config for the scorer (offline; taxonomy is replaced by the
    profile's own terms inside score_match anyway)."""
    return build_config(argparse.Namespace())


def _opp_dict(opp: Opportunity) -> dict:
    """The minimal opportunity view the scorer expects."""
    return {"title": opp.title, "short_description": opp.short_description,
            "institution": opp.institution, "country": opp.country}


def _opportunity_hits_field(opp: dict, keywords: list[str]) -> bool:
    """Does an opportunity match any field-profile keyword?

    Performs the same containment test the supervisors endpoint uses (topics /
    department), extended to field/subfield — the two filters share the
    profile-keyword semantics so a field profile name filters both lists
    consistently."""
    haystack = " ".join([
        opp.get("field") or "",
        opp.get("subfield") or "",
        opp.get("department") or "",
        " ".join(str(t) for t in (opp.get("topics") or [])),
    ]).lower()
    return any(kw in haystack for kw in keywords)


def _compute_matches(profile: UserProfile, session: Session) -> list[dict]:
    """Score every opportunity against ``profile``, sorted best-first, and
    enrich each item with a comparative percentile (vs. the full scored list)
    plus "consider learning" suggestions for missing methods."""
    cfg = _default_cfg()
    rows: list[tuple[Opportunity, dict]] = []
    for opp in session.scalars(select(Opportunity)):
        result = score_match(profile, _opp_dict(opp), cfg)
        out = opportunity_out(opp)
        out.update(match_score=result.overall_score,
                   match_explanation=result.explanation,
                   topic_score=result.topic_score,
                   method_score=result.method_score,
                   location_score=result.location_score,
                   confidence=result.confidence)
        rows.append((opp, out))
    rows.sort(key=lambda r: -r[1]["match_score"])

    # Comparative percentile: share of scored opportunities at or below this
    # match score (ties share the same percentile).
    n = len(rows)
    if n:
        ordered = [out["match_score"] for _, out in rows]
        for opp, out in rows:
            at_or_below = sum(1 for s in ordered if s <= out["match_score"])
            percentile = 100.0 * at_or_below / n
            suggestions = missing_methods(profile, _opp_dict(opp))[:3]
            result = score_match(profile, _opp_dict(opp), cfg,
                                 percentile=percentile,
                                 suggestions=suggestions)
            out["match_explanation"] = result.explanation
            out["percentile"] = round(percentile, 1)
            out["suggestions"] = list(result.suggestions)
            out["next_actions"] = next_actions(profile, _opp_dict(opp))
    return [out for _, out in rows]


@router.get("")
def list_matches(
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    limit: int = Query(500, ge=1, le=500),
    field: str | None = Query(None, description="filter opportunities by field (e.g. astronomy, biology)"),
    row=Depends(get_active_profile_row),
    session: Session = Depends(get_db),
) -> dict:
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    profile = UserProfile(**row.to_profile())
    # Scored matches are deterministic for a given profile, so cache the full
    # list (1h TTL in core.cache) and only re-sort/paginate below.
    items = cache.get_cached_matches(row.id)
    if items is None:
        key = (CACHE_VERSION, row.id)
        with _match_cache_lock:
            if key not in _match_cache:
                _match_cache[key] = _compute_matches(profile, session)
            items = _match_cache[key]
        cache.cache_match_results(row.id, items)
    if field:
        keywords = field_profile_keywords(field)
        # Unknown profile: explicit empty result, never "match everything".
        items = ([i for i in items if _opportunity_hits_field(i, keywords)]
                 if keywords else [])
    if min_score > 0.0:
        items = [i for i in items if i["match_score"] >= min_score]
    total = len(items)
    start = (page - 1) * limit
    pages = (total + limit - 1) // limit if total else 0
    return {"items": items[start:start + limit], "total": total,
            "page": page, "limit": limit, "pages": pages}


@router.post("/{match_id}/feedback")
def submit_feedback(
    match_id: int,
    body: MatchFeedbackRequest,
    user=Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    if session.get(Opportunity, match_id) is None:
        raise HTTPException(status_code=404, detail="Match not found")
    MatchFeedbackRepo(session).create(user_id=user.id, match_id=match_id,
                                      helpful=body.helpful,
                                      comment=body.comment)
    session.commit()
    return {"status": "ok", "match_id": match_id, "helpful": body.helpful}
