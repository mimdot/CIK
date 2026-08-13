"""api.routes.profile — the user's active profile (Sprint 04, A2 / C2).

All three endpoints require auth and operate on the *authenticated user's*
profile only (``user_id`` scoping). ``POST /build`` runs the LLM extraction
from :mod:`core.profile` and stores the result as the user's active profile.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import (get_active_profile, get_active_profile_row,
                      get_current_user, get_db)
from api.routes.matches import invalidate_match_cache
from api.schemas import (BuildProfileRequest, ExtractCvRequest,
                         ExtractCvResponse, ProfileUpdate)
from core import cache
from core.cv import CvParseError, extract_cv_text
from core.llm import LLMRouter
from core.profile import extract_profile
from core.profile_schema import UserProfile
from db.models import User
from db.repositories import ProfileRepo

log = logging.getLogger("api.profile")

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Columns stored as JSON-encoded text in the DB (mirrors UserProfileRow).
_JSON_COLUMNS = ("skills", "methods", "tools", "target_roles",
                 "countries_preferred", "constraints")


def _to_db_values(fields: dict) -> dict:
    """Encode list-valued profile fields as JSON text for the update path."""
    out = {}
    for k, v in fields.items():
        if k in _JSON_COLUMNS and isinstance(v, list):
            out[k] = json.dumps(v, ensure_ascii=False)
        else:
            out[k] = v
    return out


@router.get("", response_model=dict)
def get_profile(profile: UserProfile | None = Depends(get_active_profile)) -> dict:
    if profile is None:
        raise HTTPException(status_code=404, detail="No active profile")
    return profile.model_dump()


@router.post("/extract-cv", response_model=ExtractCvResponse)
def extract_cv(body: ExtractCvRequest,
               user: User = Depends(get_current_user)) -> ExtractCvResponse:
    """Parse an uploaded CV (PDF/DOCX/TXT) to plain text — locally, never sent
    to any third party and never stored. Returns the extracted text for the
    user to review/edit before ``POST /build`` uses it."""
    payload = body.content_b64.split(",", 1)[-1]  # tolerate a data: URL prefix
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Invalid base64 file data.")
    try:
        text = extract_cv_text(body.filename, data)
    except CvParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    log.info("extracted %d chars from CV '%s' for user %s",
             len(text), body.filename, user.id)
    return ExtractCvResponse(filename=body.filename, chars=len(text),
                             raw_text=text)


@router.post("/build", response_model=dict, status_code=201)
def build_profile(body: BuildProfileRequest,
                  user: User = Depends(get_current_user),
                  session: Session = Depends(get_db)) -> dict:
    llm = LLMRouter()
    profile = extract_profile(body.raw_text, llm)
    if profile is None:
        raise HTTPException(status_code=422,
                            detail="Could not extract profile from text")
    repo = ProfileRepo(session)
    repo.deactivate_all(user_id=user.id)
    data = profile.model_dump()
    data["user_id"] = user.id
    created = repo.create(data)
    session.commit()
    invalidate_match_cache()
    cache.invalidate_matches(created.id)
    return profile.model_dump()


@router.put("", response_model=dict)
def update_profile(body: ProfileUpdate,
                   user: User = Depends(get_current_user),
                   session: Session = Depends(get_db)) -> dict:
    row = get_active_profile_row(user, session)
    if row is None:
        raise HTTPException(status_code=404, detail="No active profile")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return row.to_profile()
    row = ProfileRepo(session).update(row.id, **_to_db_values(fields))
    session.commit()
    invalidate_match_cache()
    cache.invalidate_matches(row.id)
    return row.to_profile()
