"""api.routes.opportunities — read-only access to the opportunities table
(Sprint 04, A3). Supports country/source/type filters plus pagination.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.serializers import opportunity_out
from core import cache
from db.models import Opportunity
from db.repositories import ProfileRepo

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _like(q: str) -> str:
    """Escape a free-text search term for use inside a LIKE/ILIKE pattern."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _active_profile_terms(session: Session) -> list[str]:
    """Terms of the globally active research profile — the same profile the
    engine ranks a run with (core.tasks._active_profile). Never fatal: an
    unreadable profile degrades to an unprofiled cache key."""
    try:
        from core.tasks import profile_terms
        from core.profile_schema import UserProfile
        row = ProfileRepo(session).get_active()
        if row is None:
            return []
        return profile_terms(UserProfile(**row.to_profile()))
    except Exception:
        return []


@router.get("")
def list_opportunities(
    country: str | None = Query(None, description="exact country filter"),
    source: str | None = Query(None, description="source name filter"),
    # Backward compat: 'type' matches the Opportunity model column name.
    type: str | None = Query(None, alias="type",
                             description="position type (phd/postdoc/...)"),
    q: str | None = Query(None, description="free-text search on title, "
                                            "description or institution"),
    field: str | None = Query(None, description="field profile the record was "
                                                "crawled under (e.g. chemistry)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> dict:
    # When no filters are applied the full list is stable between pipeline
    # runs, so serve it from cache (invalidated on each pipeline run). The
    # cache key carries the field: a single global key would serve the
    # astronomy list to a chemistry view for up to an hour.
    if not (country or source or type or q) and page == 1:
        # The list is RANKED by the active research profile, so it belongs to
        # that profile. Keying on field alone meant editing your keywords and
        # re-running served the previous ranking for a full hour — which is
        # indistinguishable from the profile having no effect at all.
        prof = cache.profile_fingerprint(_active_profile_terms(session))
        cached = cache.get_cached_opportunity_list(field, prof)
        if cached is not None:
            total = len(cached)
            return {"items": cached[:limit], "total": total,
                    "page": 1, "limit": limit, "field": field,
                    "pages": (total + limit - 1) // limit if total else 0}
        stmt = select(Opportunity)
        if field:
            stmt = stmt.where(Opportunity.field == field)
        full = [opportunity_out(o) for o in session.scalars(
            stmt.order_by(Opportunity.posted_date.desc().nulls_last(),
                          Opportunity.id.desc()))]
        cache.cache_opportunity_list(full, field, prof)
        total = len(full)
        return {"items": full[:limit], "total": total,
                "page": 1, "limit": limit, "field": field,
                "pages": (total + limit - 1) // limit if total else 0}

    stmt = select(Opportunity)
    if country:
        stmt = stmt.where(Opportunity.country == country)
    if source:
        stmt = stmt.where(Opportunity.source == source)
    if type:
        stmt = stmt.where(Opportunity.position_type == type)
    if field:
        stmt = stmt.where(Opportunity.field == field)
    if q:
        like = _like(q)
        stmt = stmt.where(
            or_(Opportunity.title.ilike(like, escape="\\"),
                Opportunity.short_description.ilike(like, escape="\\"),
                Opportunity.institution.ilike(like, escape="\\")))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(session.scalars(
        stmt.order_by(Opportunity.posted_date.desc().nulls_last(),
                      Opportunity.id.desc())
        .offset((page - 1) * limit).limit(limit)))
    pages = (total + limit - 1) // limit if total else 0
    return {"items": [opportunity_out(o) for o in rows],
            "total": total, "page": page, "limit": limit, "pages": pages}


@router.get("/{opportunity_id}")
def get_opportunity(opportunity_id: int,
                    session: Session = Depends(get_db)) -> dict:
    opp = session.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity_out(opp)
