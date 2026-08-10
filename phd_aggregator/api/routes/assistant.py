"""api.routes.assistant — product-AI drafting endpoints (Sprint 09, Track A2).

User-facing LLM assistance behind a soft per-user daily quota. The drafts are
NEVER auto-submitted — each endpoint returns editable text the dashboard shows
in a modal. The LLM is a drafting tool only: ranking stays deterministic.

Every endpoint:
- requires an authenticated user + an active profile;
- honors the ``ASSISTANT_ENABLED`` feature toggle (cut instantly without a
  deploy);
- is subject to a per-user soft quota (default 50 drafts/day) enforced with
  the shared Redis limiter, degrading to an in-process limiter when Redis is
  down.
"""

from __future__ import annotations

import argparse
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_active_profile, get_current_user, get_db
from api.schemas import (ApplicationEmailRequest, AssistantUsageOut,
                         CoverLetterRequest)
from core import assistant as assistant_core
from core.assistant import (assistant_enabled, draft_application_email,
                            draft_cover_letter, suggest_cv_improvements)
from core.config import build_config
from core.profile_schema import UserProfile
from core.ratelimit import RedisRateLimiter
from db.models import Opportunity, User

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# Soft per-user daily draft quota (C1 "soft per-user LLM quota").
ASSISTANT_DAILY_LIMIT = int(__import__("os").environ.get(
    "ASSISTANT_DAILY_LIMIT", "50"))
_assistant_limiter = RedisRateLimiter(ASSISTANT_DAILY_LIMIT, 24 * 3600,
                                      prefix="assistant")


@lru_cache(maxsize=1)
def _default_cfg():
    return build_config(argparse.Namespace())


def _require_enabled() -> None:
    if not assistant_enabled():
        raise HTTPException(
            status_code=404,
            detail="Assistant features are currently disabled")


def _quota_key(user: User) -> str:
    return f"user:{user.id}"


def _enforce_quota(user: User) -> None:
    key = _quota_key(user)
    if not _assistant_limiter.check(key):
        raise HTTPException(
            status_code=429,
            detail="Daily draft limit reached — try again tomorrow")


def _opp_for(opportunity_id: int, session: Session) -> dict:
    row = session.get(Opportunity, opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return {"title": row.title, "institution": row.institution,
            "country": row.country, "deadline": row.deadline,
            "funding_status": row.funding_status,
            "short_description": row.short_description, "url": row.url}


def _explain(profile: UserProfile, opp: dict) -> str:
    """Deterministic match explanation for grounding the draft (never scores)."""
    from matching import score_match
    return score_match(profile, opp, _default_cfg()).explanation


def _ensure_profile(profile: UserProfile | None) -> UserProfile:
    if profile is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    return profile


@router.post("/cover-letter")
def cover_letter(body: CoverLetterRequest,
                 profile: UserProfile = Depends(get_active_profile),
                 user: User = Depends(get_current_user),
                 session: Session = Depends(get_db)) -> dict:
    """Draft an editable cover letter for one opportunity."""
    _require_enabled()
    profile = _ensure_profile(profile)
    _enforce_quota(user)
    opp = _opp_for(body.opportunity_id, session)
    opp["match_explanation"] = _explain(profile, opp)
    return draft_cover_letter(profile, opp, tone=body.tone or "professional",
                              length=body.length or "medium",
                              user_id=user.id)


@router.post("/application-email")
def application_email(body: ApplicationEmailRequest,
                      profile: UserProfile = Depends(get_active_profile),
                      user: User = Depends(get_current_user),
                      session: Session = Depends(get_db)) -> dict:
    """Draft a short email to the PI / contact."""
    _require_enabled()
    profile = _ensure_profile(profile)
    _enforce_quota(user)
    opp = _opp_for(body.opportunity_id, session)
    opp["match_explanation"] = _explain(profile, opp)
    return draft_application_email(profile, opp, user_id=user.id)


@router.post("/cv-improvements")
def cv_improvements(profile: UserProfile = Depends(get_active_profile),
                    user: User = Depends(get_current_user),
                    session: Session = Depends(get_db),
                    top_n: int = Query(10, ge=1, le=50)) -> dict:
    """Skill/tool gaps from the user's strongest matches, as suggestions."""
    _require_enabled()
    profile = _ensure_profile(profile)
    _enforce_quota(user)

    from api.routes.matches import _compute_matches
    matches = _compute_matches(profile, session)
    gaps: list[str] = []
    for m in matches[:top_n]:
        if float(m.get("match_score") or 0.0) < 0.6:
            break
        for s in m.get("suggestions") or []:
            if s not in gaps:
                gaps.append(s)
    return suggest_cv_improvements(profile, gaps=gaps[:5], user_id=user.id)


@router.get("/usage", response_model=AssistantUsageOut)
def usage(user: User = Depends(get_current_user)) -> dict:
    """Per-user daily draft usage (limit / used / remaining)."""
    key = _quota_key(user)
    remaining = _assistant_limiter.remaining(key)
    return {"limit": ASSISTANT_DAILY_LIMIT,
            "used": max(0, ASSISTANT_DAILY_LIMIT - remaining),
            "remaining": remaining}
