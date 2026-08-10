"""api.routes.supervisors — ranked supervisor candidates (Sprint 04, A4).
Reads the supervisors table ranked by fit_score, with optional country/field
filters.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from api.serializers import supervisor_out
from core import cache
from db.repositories import SupervisorRepo

router = APIRouter(prefix="/api/supervisors", tags=["supervisors"])


@router.get("")
def list_supervisors(
    country: str | None = Query(None, description="exact country filter"),
    field: str | None = Query(None, description="topic/department substring"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> dict:
    # Unfiltered list is stable between data refreshes; serve from cache.
    if not (country or field):
        cached = cache.get_cached_supervisor_list()
        if cached is not None:
            return {"items": cached[:limit], "total": len(cached),
                    "limit": limit}
        rows = SupervisorRepo(session).search()
        full = [supervisor_out(s) for s in rows]
        cache.cache_supervisor_list(full)
        return {"items": full[:limit], "total": len(full), "limit": limit}
    rows = SupervisorRepo(session).search(country=country, field=field,
                                          limit=limit)
    return {"items": [supervisor_out(s) for s in rows], "total": len(rows),
            "limit": limit}


@router.get("/{supervisor_id}")
def get_supervisor(supervisor_id: int,
                   session: Session = Depends(get_db)) -> dict:
    row = SupervisorRepo(session).get_by_id(supervisor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    return supervisor_out(row)
