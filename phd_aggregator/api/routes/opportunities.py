"""api.routes.opportunities — read-only access to the opportunities table
(Sprint 04, A3). Supports country/source/type filters plus pagination.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.serializers import opportunity_out
from core import cache
from db.models import Opportunity

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


@router.get("")
def list_opportunities(
    country: str | None = Query(None, description="exact country filter"),
    source: str | None = Query(None, description="source name filter"),
    # Backward compat: 'type' matches the Opportunity model column name.
    type: str | None = Query(None, alias="type",
                             description="position type (phd/postdoc/...)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> dict:
    # When no filters are applied the full list is stable between pipeline
    # runs, so serve it from cache (invalidated on each pipeline run).
    if not (country or source or type) and page == 1:
        cached = cache.get_cached_opportunity_list()
        if cached is not None:
            total = len(cached)
            return {"items": cached[:limit], "total": total,
                    "page": 1, "limit": limit,
                    "pages": (total + limit - 1) // limit if total else 0}
        full = [opportunity_out(o) for o in session.scalars(
            select(Opportunity).order_by(
                Opportunity.posted_date.desc().nulls_last(),
                Opportunity.id.desc()))]
        cache.cache_opportunity_list(full)
        total = len(full)
        return {"items": full[:limit], "total": total,
                "page": 1, "limit": limit,
                "pages": (total + limit - 1) // limit if total else 0}

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
