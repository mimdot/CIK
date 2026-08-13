"""api.routes.supervisors — ranked supervisor candidates (Sprint 04, A4).
Reads the supervisors table ranked by fit_score, with optional country/field
filters, plus a job that re-runs the finder chain online (the desktop app's
"run online search" button).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas import SupervisorRunRequest
from api.serializers import supervisor_out
from core import cache, tasks
from core.config import field_profile_keywords
from db.models import User
from db.repositories import SupervisorRepo

log = logging.getLogger("api.supervisors")

router = APIRouter(prefix="/api/supervisors", tags=["supervisors"])


@router.get("")
def list_supervisors(
    country: str | None = Query(None, description="exact country filter"),
    field: str | None = Query(None, description="field profile name (e.g. astronomy, biology)"),
    q: str | None = Query(None, description="free-text search on name, "
                                            "institution, department or topics"),
    limit: int = Query(500, ge=1, le=500),
    session: Session = Depends(get_db),
) -> dict:
    # Unfiltered list is stable between data refreshes; serve from cache.
    if not (country or field or q):
        cached = cache.get_cached_supervisor_list()
        if cached is not None:
            return {"items": cached[:limit], "total": len(cached),
                    "limit": limit}
        rows = SupervisorRepo(session).search()
        full = [supervisor_out(s) for s in rows]
        cache.cache_supervisor_list(full)
        return {"items": full[:limit], "total": len(full), "limit": limit}

    # If field is provided, extract keywords from field profile for filtering.
    # An unknown profile expands to no keywords: return an explicit empty list
    # rather than silently matching everything.
    keywords = field_profile_keywords(field) if field else None
    if field and not keywords:
        return {"items": [], "total": 0, "limit": limit}
    rows = SupervisorRepo(session).search(country=country, field=keywords,
                                          q=q, limit=limit)
    return {"items": [supervisor_out(s) for s in rows], "total": len(rows),
            "limit": limit}


@router.post("/run", status_code=202)
def run_supervisor_search(body: SupervisorRunRequest,
                          user: User = Depends(get_current_user)) -> dict:
    """Enqueue an online supervisor search for the given country(ies) and
    optional field profile. Returns a run id pollable via ``GET /api/jobs/
    {run_id}`` (same shape as pipeline runs)."""
    countries = body.country if isinstance(body.country, list) else [body.country]
    countries = [c.strip() for c in countries if c and c.strip()]
    if not countries:
        raise HTTPException(status_code=422, detail="country must not be empty")
    if body.field:
        from core.config import list_field_profiles
        if body.field not in list_field_profiles():
            raise HTTPException(status_code=422,
                                detail=f"Unknown field profile: {body.field}")
    try:
        run_id = tasks.enqueue_supervisor_job(countries, field=body.field)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    log.info("supervisor search queued by user %s: countries=%s field=%s",
             user.email, countries, body.field)
    return {"status": "started", "run_id": run_id}


@router.get("/{supervisor_id}")
def get_supervisor(supervisor_id: int,
                   session: Session = Depends(get_db)) -> dict:
    row = SupervisorRepo(session).get_by_id(supervisor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    return supervisor_out(row)
