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
from core.cv import CvParseError, extract_cv_text, parser_support
from core.cv_extract import extract_from_text
from core.llm import LLMRouter, feature_enabled
from core.profile import extract_profile
from core.profile_schema import UserProfile
from db.models import User
from db.repositories import ProfileRepo

log = logging.getLogger("api.profile")

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Reading a CV is the one feature here that can reach an AI provider (only via
# POST /build, and only there). It is switched off with ``CV_PARSING_ENABLED=0``
# so no user spends tokens on it before we are ready — the desktop shell sets
# that by default. Nothing is deleted: flip the variable and the whole path is
# back, no rebuild and no code change.
#
# The keyword picker is unaffected on purpose, because with CV reading off it
# becomes the only way to define a research profile.
CV_FEATURE = "cv_parsing"


def cv_parsing_enabled() -> bool:
    return feature_enabled(CV_FEATURE)


def _require_cv_parsing() -> None:
    if not cv_parsing_enabled():
        raise HTTPException(
            status_code=503,
            detail=("Reading CVs is coming in a future update. Choose your "
                    "field and pick keywords instead."))

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
    _require_cv_parsing()
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


@router.get("/parser-support")
def cv_parser_support() -> dict:
    """Which CV file types this installation can actually read.

    Lets the upload control degrade to the paste path BEFORE the user picks a
    file, instead of failing after they have chosen one.

    ``enabled`` answers the prior question — whether this installation reads
    CVs at all — so the UI can show "coming in a future update" instead of an
    upload control that would only fail.
    """
    return {**parser_support(), "enabled": cv_parsing_enabled()}


@router.post("/analyse-cv")
def analyse_cv(body: BuildProfileRequest,
               field: str | None = None,
               user: User = Depends(get_current_user)) -> dict:
    """Read a CV WITHOUT any AI service and return editable suggestions.

    Matches the text against the vocabulary already shipped in fields/*.yaml —
    the same terms the relevance engine scores against — so every suggestion
    is a term the engine understands, and nothing here needs an API key.

    Never fails wholesale: an unrecognised CV comes back with empty lists and
    a ``reason`` explaining which case applies, so the UI can say why rather
    than showing a generic error. The result PRE-FILLS the keyword picker; the
    picker remains the source of truth.
    """
    _require_cv_parsing()
    result = extract_from_text(body.raw_text, field_hint=field)
    log.info("analysed %d chars of CV for user %s: field=%s keywords=%d",
             len(body.raw_text or ""), user.id, result.field,
             len(result.keywords))
    return result.to_dict()


@router.post("/build", response_model=dict, status_code=201)
def build_profile(body: BuildProfileRequest,
                  user: User = Depends(get_current_user),
                  session: Session = Depends(get_db)) -> dict:
    # The ONE place in this app that can reach an AI provider. With CV reading
    # switched off it is not merely unused by the UI — the router is never
    # constructed and the call is never made, so there is no request to any
    # provider and no prompt for a key.
    #
    # NOT gated wholesale like the CV endpoints, deliberately: the keyword
    # picker calls /build too, to create the very first profile for a user who
    # has no row yet. Refusing here would break the one path that has to keep
    # working. The deterministic extractor below handles it, which is what the
    # picker wanted anyway — it matches against the same fields/*.yaml
    # vocabulary the relevance engine scores on.
    profile = None
    if cv_parsing_enabled():
        profile = extract_profile(body.raw_text, LLMRouter())
    if profile is None:
        # The LLM path needs an API key that may not be configured — that is
        # what produced the bare "Could not extract profile from text". Fall
        # back to the deterministic extractor so the user always gets
        # something editable instead of a dead end.
        fallback = extract_from_text(body.raw_text)
        if not fallback.found_anything:
            raise HTTPException(
                status_code=422,
                detail=(fallback.notes[0] if fallback.notes else
                        "Could not recognise anything in this text. Choose "
                        "your field and pick keywords directly instead."))
        log.info("LLM extraction unavailable — used the deterministic "
                 "extractor for user %s", user.id)
        profile = UserProfile(
            domain=fallback.field or "",
            subfield=(fallback.subfields[0] if fallback.subfields else None),
            methods=[], tools=fallback.tools, skills=fallback.keywords,
            experience_level=fallback.experience_level or "unknown",
            target_roles=[], countries_preferred=fallback.countries,
            constraints=[],
            # Deliberately low: this is a keyword match, not comprehension.
            # The user is expected to review and edit it.
            confidence=0.4,
            raw_text=body.raw_text)
    repo = ProfileRepo(session)
    repo.deactivate_all(user_id=user.id)
    data = profile.model_dump()
    data["user_id"] = user.id
    created = repo.create(data)
    session.commit()
    invalidate_match_cache()
    cache.invalidate_matches(created.id)
    # The opportunity list is RANKED by the profile, so a new profile makes
    # every cached page wrong. Without this, editing your keywords and
    # re-running looks exactly like "the profile has no effect" for a full TTL.
    cache.invalidate_opportunities()
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
    cache.invalidate_opportunities()
    return row.to_profile()
