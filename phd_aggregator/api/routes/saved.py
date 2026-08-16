"""api.routes.saved — saved opportunities and supervisors.

Replaces ``/api/bookmarks``. Two things it does that bookmarks could not:

* keys each entry by the record's own identity rather than a row id, so a
  re-crawl cannot turn a saved position into a different one, and
* stores a snapshot, so an entry still reads correctly after the source page
  is taken down — which is when you most want to look at it.

Whether an entry is *still listed* is answered by looking its key up in the
live table on every read, so it can never be a stale flag nobody cleared.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas import SavedCreate, SavedUpdate
from api.serializers import opportunity_out, supervisor_out
from core.saved_keys import key_for
from db.models import Opportunity, SavedItem, Supervisor, User

router = APIRouter(prefix="/api/saved", tags=["saved"])

KINDS = ("opportunity", "supervisor")
STATUSES = ("interested", "applied", "rejected")


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=422,
                            detail=f"kind must be one of {', '.join(KINDS)}")
    return kind


def _live_record(kind: str, record_id: int, session: Session) -> dict:
    """The record as it stands right now, or 404."""
    if kind == "opportunity":
        row = session.get(Opportunity, record_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return opportunity_out(row)
    row = session.get(Supervisor, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    return supervisor_out(row)


def _live_index(kind: str, session: Session) -> dict[str, int]:
    """Stable key -> the id of the live row that currently has it.

    Computed per request rather than cached: a saved item going missing is
    exactly the state the user needs to be told about, and a cache is how that
    news arrives late. It also gives the frontend the *current* row id for a
    saved item, which is the only honest way to link one back to a live card —
    the id it was saved under may no longer exist.
    """
    if kind == "opportunity":
        rows = session.scalars(select(Opportunity)).all()
        return {key_for("opportunity", opportunity_out(r)): r.id for r in rows}
    rows = session.scalars(select(Supervisor)).all()
    return {key_for("supervisor", supervisor_out(r)): r.id for r in rows}


def _out(item: SavedItem, live_id: int | None) -> dict:
    try:
        snapshot = json.loads(item.snapshot)
    except (ValueError, TypeError):
        snapshot = {}
    return {
        "id": item.id,
        "kind": item.kind,
        "stable_key": item.stable_key,
        "record": snapshot,
        "note": item.note,
        "status": item.status or "interested",
        "still_listed": live_id is not None,
        "record_id": live_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("")
def list_saved(kind: str = Query(...),
               user: User = Depends(get_current_user),
               session: Session = Depends(get_db)) -> dict:
    _check_kind(kind)
    items = list(session.scalars(
        select(SavedItem)
        .where(SavedItem.user_id == user.id, SavedItem.kind == kind)
        .order_by(SavedItem.created_at.desc())))
    live = _live_index(kind, session) if items else {}
    return {
        "items": [_out(i, live.get(i.stable_key)) for i in items],
        "total": len(items),
    }


@router.get("/ids")
def saved_ids(kind: str = Query(...),
              user: User = Depends(get_current_user),
              session: Session = Depends(get_db)) -> dict:
    """Live record id -> saved-item id, for every currently-listed saved record.

    A list of cards knows row ids, not stable keys, and deriving the key in the
    browser would mean a second copy of the normalisation rules drifting away
    from this one. So the mapping is resolved here, once per list, instead of
    one request per card.
    """
    _check_kind(kind)
    saved = list(session.scalars(
        select(SavedItem)
        .where(SavedItem.user_id == user.id, SavedItem.kind == kind)))
    live = _live_index(kind, session) if saved else {}
    ids = {str(live[i.stable_key]): i.id for i in saved if i.stable_key in live}
    return {"ids": ids}


@router.post("", status_code=201)
def create_saved(body: SavedCreate,
                 user: User = Depends(get_current_user),
                 session: Session = Depends(get_db)) -> dict:
    kind = _check_kind(body.kind)
    record = _live_record(kind, body.record_id, session)
    key = key_for(kind, record)

    existing = session.scalars(
        select(SavedItem).where(SavedItem.user_id == user.id,
                                SavedItem.kind == kind,
                                SavedItem.stable_key == key)).first()
    if existing is not None:
        # Saving something already saved is not an error — it is the user
        # pressing a toggle they cannot see the state of yet.
        return _out(existing, body.record_id)

    item = SavedItem(user_id=user.id, kind=kind, stable_key=key,
                     snapshot=json.dumps(record), note=body.note,
                     status=body.status or "interested")
    session.add(item)
    session.commit()
    return _out(item, body.record_id)


@router.patch("/{item_id}")
def update_saved(item_id: int, body: SavedUpdate,
                 user: User = Depends(get_current_user),
                 session: Session = Depends(get_db)) -> dict:
    item = session.get(SavedItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    if body.note is not None:
        item.note = body.note
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {', '.join(STATUSES)}")
        item.status = body.status
    session.commit()
    return _out(item, _live_index(item.kind, session).get(item.stable_key))


@router.delete("/{item_id}")
def delete_saved(item_id: int,
                 user: User = Depends(get_current_user),
                 session: Session = Depends(get_db)) -> dict:
    item = session.get(SavedItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(item)
    session.commit()
    return {"status": "deleted"}
