"""api.routes.email — email lifecycle endpoints (Sprint 07, Track A4).

- ``POST /api/email/webhook`` — receives Resend bounce/complaint events and
  records them in ``email_events`` (signature-verified when
  ``RESEND_WEBHOOK_SECRET`` is set; dev mode accepts without a secret so the
  suite stays offline).
- ``GET /api/email/unsubscribe`` — one-click unsubscribe via a signed HMAC
  token (see :func:`api.security.hmac_sign`); flips the user's digest
  preference to ``never``.
- ``POST /api/email/preview-digest`` — renders the caller's current digest as
  HTML without sending (Settings-page preview).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.security import hmac_verify, log_audit
from db.models import User
from db.repositories import EmailEventRepo

log = logging.getLogger("api.email")

router = APIRouter(prefix="/api/email", tags=["email"])

# Webhooks signed/replayed longer ago than this are rejected outright (defeats
# replay: an attacker can resend a captured old event, but not within the
# freshness window). A small tolerance either side absorbs NTP clock drift.
WEBHOOK_MAX_AGE_SECONDS = 300  # 5 minutes


def _webhook_secret() -> str:
    return os.environ.get("RESEND_WEBHOOK_SECRET", "").strip()


def _fresh_timestamp(webhook_ts: str,
                     max_age: float = WEBHOOK_MAX_AGE_SECONDS) -> bool:
    """True when the ``webhook-timestamp`` header is recent (unreplayed).

    Non-numeric or out-of-window timestamps fail closed so a captured old
    webhook cannot be replayed against this endpoint."""
    try:
        ts = float(webhook_ts)
    except (TypeError, ValueError):
        return False
    return abs(time.time() - ts) <= max_age


def verify_webhook_signature(request: Request, body: bytes,
                             max_age: float = WEBHOOK_MAX_AGE_SECONDS) -> bool:
    """Validate the Resend webhook signature when a secret is configured.

    Resend signs webhooks with an ``Svix-Signature`` header (HMAC-SHA256 over
    ``webhook-id.webhook-timestamp.<body>``). When ``RESEND_WEBHOOK_SECRET`` is
    unset (dev/test) any payload is accepted so the suite stays offline.

    With a secret set we also enforce ``webhook-timestamp`` freshness
    (``max_age`` seconds) so a recorded webhook cannot be replayed later.
    """
    secret = _webhook_secret()
    if not secret:
        return True
    if not _fresh_timestamp(request.headers.get("webhook-timestamp", ""),
                            max_age=max_age):
        return False
    signature = request.headers.get("Svix-Signature", "")
    if not signature:
        return False
    # Header may be "v1,base64sig" or a comma-separated list of candidates.
    base64_sig = ""
    for part in signature.split(" "):
        if part.startswith("v1,"):
            base64_sig = part.split(",", 1)[1]
            break
    if not base64_sig:
        return False
    webhook_id = request.headers.get("webhook-id", "")
    webhook_ts = request.headers.get("webhook-timestamp", "")
    signed_content = f"{webhook_id}.{webhook_ts}.".encode("utf-8") + body
    try:
        expected = base64.b64decode(base64_sig)
    except Exception:
        return False
    digest = hmac.new(secret.encode("utf-8"), signed_content,
                      hashlib.sha256).digest()
    return hmac.compare_digest(digest, expected)


class _WebhookBody(BaseModel):
    type: str = ""          # email.bounced | email.complained | ...
    email: str = ""
    data: dict = {}
    id: Optional[str] = None
    subject: Optional[str] = None


@router.post("/webhook", status_code=200)
async def email_webhook(request: Request,
                        session: Session = Depends(get_db)) -> dict:
    """Record a Resend bounce/complaint event. Idempotent-ish: each event is
    stored as its own row. Returns 200 (Resend treats non-2xx as a retry)."""
    body = await request.body()
    if not verify_webhook_signature(request, body):
        raise HTTPException(status_code=401, detail="Bad webhook signature")
    try:
        payload = _WebhookBody.model_validate_json(body or b"{}")
    except Exception:
        payload = _WebhookBody()
    event_type = (payload.type or "email.unknown").replace("email.", "")
    email_to = payload.email or (payload.data or {}).get("email")
    if event_type in ("bounced", "complained", "failed"):
        EmailEventRepo(session).record(
            email_to=email_to or "unknown", event_type=event_type,
            subject=payload.subject,
            provider_id=payload.id,
            detail=payload.data or payload.model_dump())
        session.commit()
        log.info("email webhook: %s -> %s", event_type, email_to)
    return {"status": "ok", "received": event_type}


@router.get("/unsubscribe")
def unsubscribe(token: str = Query(..., description="signed unsubscribe token"),
                session: Session = Depends(get_db)) -> dict:
    """One-click unsubscribe. The token is ``hmac_sign(profile_id)`` embedded
    in every digest email; verifying it proves the recipient owns the link."""
    value = hmac_verify(token)
    if value is None or not value.isdigit():
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    profile_id = int(value)
    from db.models import DigestPreference
    pref = session.get(DigestPreference, profile_id)
    if pref is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    pref.frequency = "never"
    EmailEventRepo(session).record(
        email_to=pref.email or "unknown", event_type="unsubscribed",
        subject="digest unsubscribe")
    log_audit(session, action="email.unsubscribe", actor_type="user",
              target_type="profile", target_id=profile_id)
    session.commit()
    return {"status": "unsubscribed", "profile_id": profile_id}


@router.post("/preview-digest")
def preview_digest(user: User = Depends(get_current_user),
                   session: Session = Depends(get_db)) -> dict:
    """Render the caller's current weekly digest (no send). Used by the
    Settings page to show what the next email will look like."""
    from api.deps import get_active_profile_row
    from core.config import build_config
    from core.digest import build_digest
    from core.profile_schema import UserProfile
    from sqlalchemy import select

    row = get_active_profile_row(user, session)
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    profile = UserProfile(**row.to_profile())
    import argparse
    cfg = build_config(argparse.Namespace())
    from db.models import Opportunity
    from matching import score_many
    opps = list(session.scalars(select(Opportunity)))
    opp_dicts = [
        {"title": o.title, "short_description": o.short_description,
         "institution": o.institution, "country": o.country}
        for o in opps
    ]
    results = score_many(profile, opp_dicts, cfg)
    scored = [{
        "title": opp.title, "institution": opp.institution,
        "country": opp.country, "url": opp.url, "deadline": opp.deadline,
        "funding_status": opp.funding_status,
        "match_score": result.overall_score,
        "match_explanation": result.explanation,
    } for opp, result in zip(opps, results)]
    from db.models import DigestPreference
    pref = session.get(DigestPreference, row.id)
    include_sup = bool(pref.include_supervisors) if pref else False
    digest = build_digest(profile, positions=scored,
                          supervisors=[], include_supervisors=include_sup)
    return {"subject": digest["subject"], "html": digest["html"],
            "text": digest["text"]}


# Re-export so app wiring stays stable.
__all__ = ["router"]