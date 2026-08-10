"""api.routes.account — data-subject (GDPR) endpoints (Sprint 10, D2).

Scoped to the authenticated user:

- ``GET /api/account/data-export`` — a machine-readable copy of everything the
  platform holds about the user (profile, matches, bookmarks, applications,
  API keys, feedback, LLM usage, audit trail, digest + consent prefs).
- ``DELETE /api/account`` — right-to-erasure. Hard-deletes the user's own
  records (profiles, bookmarks, applications, API keys, reset/verify tokens)
  and ANONYMIZES analytics rows (feedback, LLM usage, audit trail) by dropping
  the user link, so aggregate statistics survive without identifying anyone.
- ``GET/PUT /api/account/consent`` — read/update the marketing-email consent.

Nothing here ever touches another user's data; every query is filtered by the
authenticated ``user.id``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.security import log_audit
from db.models import (ApiKey, ApiKeyUsage, Application, AuditEvent,
                       Bookmark, DigestPreference, EmailEvent,
                       EmailVerification, Invite, LlmUsage, Match,
                       MatchFeedback, PasswordReset, User, UserProfileRow)

router = APIRouter(prefix="/api/account", tags=["account"])


class ConsentUpdate(BaseModel):
    marketing_email: bool


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _profile_out(row: UserProfileRow) -> dict:
    return {
        "id": row.id,
        "active": row.active,
        "domain": row.domain,
        "subfield": row.subfield,
        "skills": json.loads(row.skills) if row.skills else [],
        "methods": json.loads(row.methods) if row.methods else [],
        "tools": json.loads(row.tools) if row.tools else [],
        "target_roles": json.loads(row.target_roles) if row.target_roles else [],
        "countries_preferred": (json.loads(row.countries_preferred)
                                if row.countries_preferred else []),
        "funding_requirement": row.funding_requirement,
        "constraints": json.loads(row.constraints) if row.constraints else [],
        "experience_level": row.experience_level,
        "confidence": row.confidence,
        "raw_text": row.raw_text,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _match_out(row: Match) -> dict:
    return {
        "id": row.id,
        "profile_id": row.profile_id,
        "target_type": row.target_type,
        "opportunity_id": row.opportunity_id,
        "supervisor_id": row.supervisor_id,
        "overall_score": row.overall_score,
        "topic_score": row.topic_score,
        "method_score": row.method_score,
        "skill_score": row.skill_score,
        "location_score": row.location_score,
        "funding_score": row.funding_score,
        "competitiveness_score": row.competitiveness_score,
        "explanation": row.explanation,
        "created_at": _iso(row.created_at),
    }


def _bookmark_out(row: Bookmark) -> dict:
    return {"id": row.id, "opportunity_id": row.opportunity_id,
            "created_at": _iso(row.created_at)}


def _application_out(row: Application) -> dict:
    return {"id": row.id, "opportunity_id": row.opportunity_id,
            "status": row.status, "cover_letter": row.cover_letter,
            "outcome": row.outcome, "applied_at": _iso(row.applied_at),
            "created_at": _iso(row.created_at)}


def _key_out(row: ApiKey) -> dict:
    return {"id": row.id, "name": row.name, "key_prefix": row.key_prefix,
            "scopes": json.loads(row.scopes) if row.scopes else [],
            "last_used_at": _iso(row.last_used_at),
            "expires_at": _iso(row.expires_at), "created_at": _iso(row.created_at)}


@router.get("/data-export")
def export_data(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """A complete JSON copy of the authenticated user's data."""
    profiles = (session.query(UserProfileRow)
                .filter(UserProfileRow.user_id == user.id)
                .order_by(UserProfileRow.id).all())
    profile_ids = [p.id for p in profiles]
    matches = (session.query(Match)
               .filter(Match.profile_id.in_(profile_ids))
               .order_by(Match.id).all()) if profile_ids else []
    feedback = (session.query(MatchFeedback)
                .filter(MatchFeedback.user_id == user.id)
                .order_by(MatchFeedback.id).all())
    bookmarks = (session.query(Bookmark)
                 .filter(Bookmark.profile_id.in_(profile_ids))
                 .order_by(Bookmark.id).all()) if profile_ids else []
    applications = (session.query(Application)
                    .filter(Application.profile_id.in_(profile_ids))
                    .order_by(Application.id).all()) if profile_ids else []
    keys = (session.query(ApiKey)
            .filter(ApiKey.user_id == user.id)
            .order_by(ApiKey.id).all())
    llm_usage = (session.query(LlmUsage)
                 .filter(LlmUsage.user_id == user.id)
                 .order_by(LlmUsage.created_at).all())
    audit = (session.query(AuditEvent)
             .filter(AuditEvent.actor_type == "user",
                     AuditEvent.actor_id == user.id)
             .order_by(AuditEvent.created_at).all())
    digests = [session.get(DigestPreference, pid) for pid in profile_ids]
    invites_used = (session.query(Invite)
                    .filter(Invite.used_by == user.id).all())

    return {
        "exported_at": datetime.now().isoformat(),
        "account": {
            "email": user.email,
            "role": user.role,
            "email_verified": user.email_verified,
            "marketing_consent": user.marketing_consent,
            "created_at": _iso(user.created_at),
        },
        "profiles": [_profile_out(p) for p in profiles],
        "digest_preferences": [
            {"profile_id": d.profile_id, "email": d.email,
             "frequency": d.frequency,
             "include_matches": d.include_matches,
             "include_supervisors": d.include_supervisors,
             "timezone": d.timezone}
            for d in digests if d is not None],
        "matches": [_match_out(m) for m in matches],
        "feedback": [
            {"id": f.id, "match_id": f.match_id,
             "target_type": f.target_type, "helpful": f.helpful,
             "comment": f.comment, "created_at": _iso(f.created_at)}
            for f in feedback],
        "bookmarks": [_bookmark_out(b) for b in bookmarks],
        "applications": [_application_out(a) for a in applications],
        "api_keys": [_key_out(k) for k in keys],
        "llm_usage": [
            {"id": u.id, "feature": u.feature, "model": u.model,
             "prompt_tokens": u.prompt_tokens,
             "completion_tokens": u.completion_tokens,
             "latency_ms": u.latency_ms, "created_at": _iso(u.created_at)}
            for u in llm_usage],
        "audit_trail": [
            {"id": a.id, "action": a.action, "target_type": a.target_type,
             "target_id": a.target_id, "meta": a.meta,
             "created_at": _iso(a.created_at)}
            for a in audit],
        "invites_used": [
            {"id": i.id, "code": i.code, "used_at": _iso(i.used_at)}
            for i in invites_used],
    }


@router.get("/consent")
def get_consent(
    user: User = Depends(get_current_user),
) -> dict:
    return {"marketing_email": user.marketing_consent,
            "updated_at": _iso(user.consent_updated_at)}


@router.put("/consent")
def update_consent(
    body: ConsentUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    user.marketing_consent = body.marketing_email
    user.consent_updated_at = datetime.now()
    log_audit(session, action="account.consent", actor_type="user",
              actor_id=user.id, ip=request.client.host if request.client else None,
              user_agent=request.headers.get("user-agent"),
              meta={"marketing_email": body.marketing_email})
    session.commit()
    return {"marketing_email": user.marketing_consent,
            "updated_at": _iso(user.consent_updated_at)}


@router.delete("")
def erase_account(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """Right-to-erasure: hard-delete PII, anonymize analytics, remove the user.

    Analytics rows that other users might implicitly depend on (feedback,
    LLM usage, audit trail) keep their row but lose the link to this account.
    The audit write happens BEFORE the rows are touched so the request itself
    is preserved.
    """
    deleted, anonymized = _erase(session, user)
    log_audit(session, action="account.delete", actor_type="user",
              actor_id=None, ip=request.client.host if request.client else None,
              user_agent=request.headers.get("user-agent"),
              meta={"email": user.email})
    session.commit()
    return {"status": "deleted", "deleted": deleted, "anonymized": anonymized}


def _erase(session: Session, user: User):
    """Perform the deletion/anonymization; returns (deleted, anonymized)."""
    deleted, anonymized = [], []
    profile_ids = [p.id for p in session.query(UserProfileRow)
                   .filter(UserProfileRow.user_id == user.id).all()]

    # --- anonymize (keep the rows for aggregate analytics, drop identity) ---
    fb = (session.query(MatchFeedback)
          .filter(MatchFeedback.user_id == user.id).all())
    for row in fb:
        row.user_id = None
    if fb:
        anonymized.append("match_feedback")

    lu = (session.query(LlmUsage).filter(LlmUsage.user_id == user.id).all())
    for row in lu:
        row.user_id = None
    if lu:
        anonymized.append("llm_usage")

    ae = (session.query(AuditEvent)
          .filter(AuditEvent.actor_type == "user",
                  AuditEvent.actor_id == user.id).all())
    for row in ae:
        row.actor_id = None
    if ae:
        anonymized.append("audit_events")

    ee = (session.query(EmailEvent)
          .filter(EmailEvent.email_to == user.email).all())
    for row in ee:
        row.email_to = None
    if ee:
        anonymized.append("email_events")

    # --- hard-delete the user's own PII --------------------------------------
    if profile_ids:
        session.query(Match).filter(Match.profile_id.in_(profile_ids)).delete(
            synchronize_session=False)
        session.query(Bookmark).filter(
            Bookmark.profile_id.in_(profile_ids)).delete(
                synchronize_session=False)
        session.query(Application).filter(
            Application.profile_id.in_(profile_ids)).delete(
                synchronize_session=False)
        session.query(DigestPreference).filter(
            DigestPreference.profile_id.in_(profile_ids)).delete(
                synchronize_session=False)
        session.query(UserProfileRow).filter(
            UserProfileRow.user_id == user.id).delete(synchronize_session=False)
        deleted.append("profiles")

    key_ids = [k.id for k in session.query(ApiKey)
               .filter(ApiKey.user_id == user.id).all()]
    if key_ids:
        session.query(ApiKeyUsage).filter(
            ApiKeyUsage.key_id.in_(key_ids)).delete(synchronize_session=False)
        session.query(ApiKey).filter(ApiKey.user_id == user.id).delete(
            synchronize_session=False)
        deleted.append("api_keys")

    session.query(PasswordReset).filter(
        PasswordReset.user_id == user.id).delete(synchronize_session=False)
    session.query(EmailVerification).filter(
        EmailVerification.user_id == user.id).delete(synchronize_session=False)
    session.query(Invite).filter(Invite.used_by == user.id).update(
        {"used_by": None, "used_at": None}, synchronize_session=False)

    session.delete(user)
    deleted.append("user")
    return deleted, anonymized
