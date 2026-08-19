"""api.routes.bookmarks — saved positions (Sprint 04, A5 / C2). Scoped to the
authenticated user's active profile. CRUD: list, create, delete.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_active_profile_row, get_current_user, get_db
from api.schemas import BookmarkCreate
from api.serializers import bookmark_out, opportunity_out
from db.models import Opportunity
from db.repositories import BookmarkRepo

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


@router.get("")
def list_bookmarks(
    row=Depends(get_active_profile_row),
    session: Session = Depends(get_db),
) -> dict:
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    bookmarks = BookmarkRepo(session).list_by_profile(row.id)
    items = []
    for bm in bookmarks:
        opp = session.get(Opportunity, bm.opportunity_id)
        items.append(bookmark_out(bm, opportunity_out(opp) if opp else None))
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
def create_bookmark(
    body: BookmarkCreate,
    row=Depends(get_active_profile_row),
    session: Session = Depends(get_db),
) -> dict:
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    if session.get(Opportunity, body.opportunity_id) is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    repo = BookmarkRepo(session)
    existing = [b for b in repo.list_by_profile(row.id)
                if b.opportunity_id == body.opportunity_id]
    if existing:
        raise HTTPException(status_code=409, detail="Already bookmarked")
    bm = repo.create(row.id, body.opportunity_id)
    session.commit()
    return {"id": bm.id, "opportunity_id": bm.opportunity_id}


@router.delete("/{bookmark_id}")
def delete_bookmark(
    bookmark_id: int,
    row=Depends(get_active_profile_row),
    session: Session = Depends(get_db),
) -> dict:
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    repo = BookmarkRepo(session)
    bm = repo.get(bookmark_id)
    if bm is None or bm.profile_id != row.id:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    if not repo.delete(bookmark_id, profile_id=row.id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    session.commit()
    return {"status": "ok", "bookmark_id": bookmark_id}
