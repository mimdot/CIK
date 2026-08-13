"""api.routes.invites — private-beta access codes (Sprint 06, Track C1).

Admins create one-time invite codes; new users redeem one during registration
(see :func:`api.routes.auth.register`). Invites are *opt-in*: whether the API
requires one is controlled by the ``INVITES_REQUIRED`` env var (see
:func:`invites_required`) so dev and tests keep working with zero codes.

Routes:
- ``POST /api/invites``             (admin) create a code
- ``GET  /api/invites``             (admin) list all codes + usage
- ``POST /api/invites/{code}/redeem`` (public) validate + mark a code used
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.routes.admin import get_admin_user
from api.security import log_audit
from db.models import Invite, User
from db.repositories import InviteRepo

router = APIRouter(prefix="/api/invites", tags=["invites"])


def invites_required() -> bool:
    """True when the API requires an invite code to register.

    Controlled by ``CIK_INVITE_REQUIRED`` (:func:`api.routes.auth.register`),
    which wins over the legacy ``INVITES_REQUIRED`` name. The default is OFF
    (open registration, matching the pre-existing dev/test behavior); opt into
    the private-beta gate with ``CIK_INVITE_REQUIRED=1``.
    """
    for name in ("CIK_INVITE_REQUIRED", "INVITES_REQUIRED"):
        value = os.environ.get(name)
        if value is not None:
            return value.strip().lower() in ("1", "true", "yes")
    return False


class InviteCreate(BaseModel):
    note: Optional[str] = None


class InviteOut(BaseModel):
    id: int
    code: str
    created_by: int
    used_by: Optional[int] = None
    used_at: Optional[str] = None
    used: bool = False


def _invite_out(i: Invite) -> dict:
    return {
        "id": i.id,
        "code": i.code,
        "created_by": i.created_by,
        "used_by": i.used_by,
        "used_at": i.used_at.isoformat() if i.used_at else None,
        "used": i.used_by is not None,
    }


def validate_invite_code(session: Session, code: str) -> Invite:
    """Return the invite for ``code`` if present and unused, else raise 422."""
    clean = (code or "").strip()
    if not clean:
        raise HTTPException(status_code=422,
                            detail="Invite code is required for registration")
    invite = InviteRepo(session).get_by_code(clean)
    if invite is None:
        raise HTTPException(status_code=422, detail="Invalid invite code")
    if invite.used_by is not None:
        raise HTTPException(status_code=422,
                            detail="Invite code has already been used")
    return invite


@router.post("", response_model=dict, status_code=201)
def create_invite(
    body: InviteCreate,
    user: User = Depends(get_admin_user),
    session: Session = Depends(get_db),
) -> dict:
    """Generate a single-use invite code (admin only)."""
    for _ in range(10):  # retry on the unlikely unique collision
        code = secrets.token_urlsafe(16)[:24]
        if InviteRepo(session).get_by_code(code) is None:
            break
    invite = InviteRepo(session).create(code=code, created_by=user.id)
    log_audit(session, action="admin.invite.create", actor_type="user",
              actor_id=user.id, target_type="invite", target_id=invite.id)
    session.commit()
    return _invite_out(invite)


@router.get("", response_model=dict)
def list_invites(
    user: User = Depends(get_admin_user),
    session: Session = Depends(get_db),
) -> dict:
    """All invite codes with usage (admin only)."""
    rows = InviteRepo(session).list_all()
    used = sum(1 for i in rows if i.used_by is not None)
    return {
        "items": [_invite_out(i) for i in rows],
        "created": len(rows),
        "redeemed": used,
        "pending": len(rows) - used,
    }


@router.post("/{code}/redeem", response_model=dict)
def redeem_invite(code: str, session: Session = Depends(get_db)) -> dict:
    """Validate an invite code is present + unused *without* consuming it.

    Consumption happens on successful registration (the code's ``used_by`` is
    set to the new user's id there). This endpoint is intentionally public so
    the onboarding form can check a code before the browser submits it.
    """
    invite = validate_invite_code(session, code)
    return {"valid": True, "code": invite.code}


# Keep the admin dependency importable for app wiring (re-export).
__all__ = ["router", "invites_required", "validate_invite_code"]