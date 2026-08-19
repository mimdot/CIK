"""api.routes.preferences — per-profile settings (Sprint 05 code review).

``POST /api/preferences`` persists the email-digest toggle to the
``DigestPreference`` table, scoped to the authenticated user's active
profile. ``GET /api/preferences`` returns the current value so the
Settings page can render the saved state.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_active_profile_row, get_db
from db.models import DigestPreference

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class DigestPreferenceUpdate(BaseModel):
    """The dashboard's digest toggle. ``frequency`` is the raw column value;
    ``digest_enabled`` is the friendly boolean form stored for the API."""

    digest_enabled: bool


def _digest_out(pref: Optional[DigestPreference]) -> dict:
    if pref is None:
        return {"digest_enabled": False, "frequency": None}
    return {
        "digest_enabled": pref.frequency not in (None, "", "never"),
        "frequency": pref.frequency,
    }


@router.get("")
def get_preferences(
    row=Depends(get_active_profile_row),
    session: Session = Depends(get_db),
) -> dict:
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    return _digest_out(session.get(DigestPreference, row.id))


@router.post("")
def update_preferences(
    body: DigestPreferenceUpdate,
    row=Depends(get_active_profile_row),
    session: Session = Depends(get_db),
) -> dict:
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    pref = session.get(DigestPreference, row.id)
    if pref is None:
        pref = DigestPreference(profile_id=row.id)
        session.add(pref)
    pref.frequency = "weekly" if body.digest_enabled else "never"
    session.commit()
    return _digest_out(pref)
