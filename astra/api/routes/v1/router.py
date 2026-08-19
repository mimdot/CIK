"""api.routes.v1 — versioned public REST API (Sprint 08, Track B3).

Exposes a stable, documented subset of the platform under ``/api/v1`` for
third-party developers. Callers authenticate with a Bearer API key
(``cik_...``) or user JWT; every route is gated by a scope and by
:func:`api.deps.enforce_api_limits` (per-key rate limit + daily quota).

Response contract: lists return ``{"data": [...], "meta": {page, limit,
total, pages}}``; single resources return ``{"data": {...}}``; errors follow
``{"error": {"code", "message", "detail"?}}`` (see the exception handlers in
:mod:`api.app`). The internal routes stay at their current paths and are
untouched (backwards-compatibility release rule).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import enforce_api_limits, get_db, require_scope
from api.routes.matches import _compute_matches
from api.schemas import BookmarkCreate, MatchFeedbackV1
from api.serializers import opportunity_out, supervisor_out
from core import cache
from core.profile_schema import UserProfile
from db.models import Opportunity
from db.repositories import (BookmarkRepo, MatchFeedbackRepo, ProfileRepo,
                             SupervisorRepo)

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _meta(page: int, limit: int, total: int) -> dict:
    return {"page": page, "limit": limit, "total": total,
            "pages": (total + limit - 1) // limit if total else 0}


def _no_profile() -> HTTPException:
    return HTTPException(status_code=404, detail="No active profile — "
                                                 "build one first")


def _active_profile(principal, session):
    """The API key/user's active profile row, or None."""
    return ProfileRepo(session).get_active(user_id=principal.user_id)


@router.get("/me")
def v1_me(
    principal=Depends(require_scope("read:profile")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """The caller's active profile (or ``data: null`` when none exists)."""
    row = _active_profile(principal, session)
    return {"data": row.to_profile() if row else None}


@router.get("/matches")
def v1_matches(
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    principal=Depends(require_scope("read:matches")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """Scored opportunity matches for the caller's active profile."""
    row = _active_profile(principal, session)
    if row is None:
        raise _no_profile()
    profile = UserProfile(**row.to_profile())
    items = cache.get_cached_matches(row.id)
    if items is None:
        items = _compute_matches(profile, session)
        cache.cache_match_results(row.id, items)
    if min_score > 0.0:
        items = [i for i in items if i["match_score"] >= min_score]
    total = len(items)
    start = (page - 1) * limit
    return {"data": items[start:start + limit],
            "meta": _meta(page, limit, total)}


@router.get("/opportunities")
def v1_opportunities(
    country: str | None = Query(None, description="exact country filter"),
    source: str | None = Query(None, description="source name filter"),
    type: str | None = Query(None, alias="type",
                             description="position type (phd/postdoc/...)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    principal=Depends(require_scope("read:opportunities")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """Paginated opportunities with the same filters as the internal API."""
    stmt = select(Opportunity)
    if country:
        stmt = stmt.where(Opportunity.country == country)
    if source:
        stmt = stmt.where(Opportunity.source == source)
    if type:
        stmt = stmt.where(Opportunity.position_type == type)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(session.scalars(
        stmt.order_by(Opportunity.posted_date.desc().nulls_last(),
                      Opportunity.id.desc())
        .offset((page - 1) * limit).limit(limit)))
    return {"data": [opportunity_out(o) for o in rows],
            "meta": _meta(page, limit, total)}


@router.get("/supervisors")
def v1_supervisors(
    country: str | None = Query(None, description="exact country filter"),
    field: str | None = Query(None, description="topic/department substring"),
    limit: int = Query(20, ge=1, le=100),
    principal=Depends(require_scope("read:supervisors")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """Ranked supervisor candidates (no pagination, by design of the source)."""
    rows = SupervisorRepo(session).search(country=country, field=field,
                                          limit=limit)
    return {"data": [supervisor_out(s) for s in rows],
            "meta": {"total": len(rows), "limit": limit}}


@router.post("/bookmarks", status_code=201)
def v1_create_bookmark(
    body: BookmarkCreate,
    principal=Depends(require_scope("write:bookmarks")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """Bookmark an opportunity for the caller's active profile."""
    row = _active_profile(principal, session)
    if row is None:
        raise _no_profile()
    if session.get(Opportunity, body.opportunity_id) is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    repo = BookmarkRepo(session)
    existing = [b for b in repo.list_by_profile(row.id)
                if b.opportunity_id == body.opportunity_id]
    if existing:
        raise HTTPException(status_code=409, detail="Already bookmarked")
    bm = repo.create(row.id, body.opportunity_id)
    session.commit()
    return {"data": {"id": bm.id, "opportunity_id": bm.opportunity_id}}


@router.delete("/bookmarks/{bookmark_id}")
def v1_delete_bookmark(
    bookmark_id: int,
    principal=Depends(require_scope("write:bookmarks")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """Remove a bookmark from the caller's active profile."""
    row = _active_profile(principal, session)
    if row is None:
        raise _no_profile()
    if not BookmarkRepo(session).delete(bookmark_id, profile_id=row.id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    session.commit()
    return {"data": {"bookmark_id": bookmark_id, "deleted": True}}


@router.post("/feedback")
def v1_feedback(
    body: MatchFeedbackV1,
    principal=Depends(require_scope("write:feedback")),
    _=Depends(enforce_api_limits),
    session: Session = Depends(get_db),
) -> dict:
    """Submit match-feedback (helps ranking quality for the caller's user)."""
    if session.get(Opportunity, body.match_id) is None:
        raise HTTPException(status_code=404, detail="Match not found")
    MatchFeedbackRepo(session).create(user_id=principal.user_id,
                                      match_id=body.match_id,
                                      helpful=body.helpful,
                                      comment=body.comment)
    session.commit()
    return {"data": {"match_id": body.match_id, "helpful": body.helpful}}
