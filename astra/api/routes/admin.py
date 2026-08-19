"""api.routes.admin — operator/administration endpoints (Sprint 06, A3/C4).

Exposes live metrics about the database connection pool (A3) and, from
Sprint 06 Track C, the private-beta admin surface (invite management, job
queue, source/user metrics). Routes here are admin-only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import _get_engine, get_db, get_current_user
from api.metrics import metrics
from api.schemas import ApiKeyQuotaOverride
from api.security import log_audit
from api.serializers import api_key_out
from db.models import (ApiKey, AuditEvent, Invite, LlmUsage, Match,
                       MatchFeedback, Opportunity, Supervisor, User,
                       UserProfileRow)
from db.repositories import ApiKeyRepo, ApiKeyUsageRepo, AuditEventRepo, InviteRepo

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_admin_user(
    user: User = Depends(get_current_user),
) -> User:
    """Resolve the current user and require the admin role (403 otherwise)."""
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


@router.get("/source-health")
def admin_source_health(user: User = Depends(get_admin_user)) -> dict:
    """Per-source availability snapshot: rolling baseline, latest result,
    z-score vs baseline and drift flag (Track B1)."""
    from core.source_monitor import source_health
    return {"sources": source_health()}


@router.post("/source-health/check-drift")
def admin_check_drift(user: User = Depends(get_admin_user),
                      session: Session = Depends(get_db)) -> dict:
    """Run the drift detector and alert ops for any source that deviated from
    its rolling baseline (debounced to one alert/source/hour)."""
    from core.source_monitor import check_drift
    alerts = check_drift()
    log_audit(session, action="admin.source_drift_check", actor_type="user",
              actor_id=user.id, meta={"alerts": len(alerts)})
    session.commit()
    return {"alerts": alerts, "count": len(alerts)}


@router.get("/feedback-intel")
def admin_feedback_intel(user: User = Depends(get_admin_user),
                         session: Session = Depends(get_db)) -> dict:
    """Match-feedback intel: helpful-rate, score-bracket breakdown, source
    breakdown and comment keyword hits (Track B2)."""
    from core.feedback_intel import feedback_intel
    return feedback_intel(session)


@router.get("/tasks/dead-letters")
def admin_dead_letters(user: User = Depends(get_admin_user)) -> dict:
    """Failed jobs available for review (dead-letter review, Track B3)."""
    from core import tasks
    return {"jobs": tasks.dead_letters()}


@router.post("/tasks/{job_id}/retry")
def admin_retry_job(job_id: str, user: User = Depends(get_admin_user),
                    session: Session = Depends(get_db)) -> dict:
    """Requeue a dead-letter job (Track B3)."""
    from core import tasks
    new_id = tasks.retry_job(job_id)
    if new_id is None:
        raise HTTPException(status_code=404,
                            detail="Job not found or not retryable")
    log_audit(session, action="admin.job_retry", actor_type="user",
              actor_id=user.id, target_type="job", target_id=job_id,
              meta={"new_job_id": new_id})
    session.commit()
    return {"retried": True, "job_id": job_id, "new_job_id": new_id}


@router.get("/tasks/worker-heartbeat")
def admin_worker_heartbeat(user: User = Depends(get_admin_user)) -> dict:
    """Latest per-worker heartbeat (Track B3)."""
    from core import tasks
    return tasks.worker_heartbeat()


@router.get("/anomalies")
def admin_anomalies_snapshot(user: User = Depends(get_admin_user)) -> dict:
    """Rolling API-metrics overview + detected anomalies (side-effect free)."""
    from core import anomaly
    return anomaly.snapshot(run_alerts=False)


@router.post("/anomalies/detect")
def admin_anomalies_detect(user: User = Depends(get_admin_user),
                           session: Session = Depends(get_db)) -> dict:
    """Re-run anomaly detection against the latest rolling buckets; new
    anomalies are forwarded to ops (track B4)."""
    from core import anomaly
    data = anomaly.snapshot(run_alerts=True)
    log_audit(session, action="admin.anomaly_detect", actor_type="user",
              actor_id=user.id,
              meta={"anomalies": [a["id"] for a in data["anomalies"]]})
    session.commit()
    return data


@router.get("/pool-status")
def pool_status(user: User = Depends(get_admin_user)) -> dict:
    """Live metrics for the SQLAlchemy connection pool.

    Only meaningful for PostgreSQL (QueuePool); SQLite reports ``enabled:
    false`` since its per-thread connections are not pooled."""
    engine = _get_engine()
    pool = engine.pool
    pool_cls = pool.__class__.__name__
    if pool_cls == "QueuePool":
        try:
            status = pool.status()  # {checkedout, size_overflow, size}
        except Exception:
            status = {}
        return {
            "engine": engine.url.get_backend_name(),
            "pool": pool_cls,
            "enabled": True,
            "pool_size": pool.size(),
            "max_overflow": pool._max_overflow,
            "timeout_seconds": pool.timeout(),
            "recycle_seconds": pool._recycle,
            "status": status,
        }
    return {
        "engine": engine.url.get_backend_name(),
        "pool": pool_cls,
        "enabled": False,
    }


@router.get("/metrics")
def admin_metrics(user: User = Depends(get_admin_user),
                  session: Session = Depends(get_db)) -> dict:
    """Aggregated private-beta metrics for the admin dashboard (C4):
    source health, API metrics, user metrics, job queue and invite usage."""
    def count(model, *where):
        stmt = select(func.count()).select_from(model)
        for w in where:
            stmt = stmt.where(w)
        return session.scalar(stmt) or 0

    users_total = count(User)
    profiles_total = count(UserProfileRow)
    profiles_active = count(UserProfileRow, UserProfileRow.active.is_(True))

    # Source health: record count + most recently posted opportunity per source.
    source_rows = session.execute(
        select(Opportunity.source, func.count(Opportunity.id),
               func.max(Opportunity.posted_date))
        .group_by(Opportunity.source).order_by(Opportunity.source)).all()
    sources = [
        {"source": s, "records": c,
         "last_posted": d.isoformat() if d else None}
        for s, c, d in source_rows
    ]

    feedback_rows = session.execute(
        select(MatchFeedback.helpful, func.count(MatchFeedback.id))
        .group_by(MatchFeedback.helpful)).all()
    feedback_total = count(MatchFeedback)
    feedback_helpful = sum(c for h, c in feedback_rows if h)

    invites = InviteRepo(session).list_all()
    invite_created = len(invites)
    invite_redeemed = sum(1 for i in invites if i.used_by is not None)

    invites = InviteRepo(session).list_all()
    invite_created = len(invites)
    invite_redeemed = sum(1 for i in invites if i.used_by is not None)

    # Sprint 09 (C2): LLM usage summary from the llm_usage ledger.
    llm_rows = session.execute(
        select(LlmUsage.model, LlmUsage.prompt_tokens,
               LlmUsage.completion_tokens)).all()
    from core.llm import estimate_cost_usd
    llm_calls = len(llm_rows)
    llm_prompt = sum(p for _, p, _ in llm_rows)
    llm_completion = sum(c for _, _, c in llm_rows)
    llm_spend = round(sum(estimate_cost_usd(m, p, c)
                          for m, p, c in llm_rows), 2)

    # Sprint 09 (C2): source-health drift summary from the rolling baseline.
    try:
        from core.source_monitor import source_health
        sh = source_health()
        sh_drifted = sum(1 for r in sh if r["drift"])
        sh_erroring = sum(1 for r in sh if r["errors"])
    except Exception:
        sh, sh_drifted, sh_erroring = [], 0, 0

    from core import tasks
    jobs = tasks.jobs_snapshot()

    return {
        "users": {
            "total": users_total,
            "active": profiles_active,
            "profiles_built": profiles_total,
        },
        "content": {
            "opportunities": count(Opportunity),
            "supervisors": count(Supervisor),
            "matches": count(Match),
            "sources": sources,
            "feedback": {"total": feedback_total,
                         "helpful": feedback_helpful},
        },
        "api": metrics.snapshot(),
        "llm": {"calls": llm_calls,
                "prompt_tokens": llm_prompt,
                "completion_tokens": llm_completion,
                "estimated_spend_usd": llm_spend},
        "source_health": {"sources": len(sh), "drifted": sh_drifted,
                          "erroring": sh_erroring},
        "jobs": jobs,
        "invites": {
            "created": invite_created,
            "redeemed": invite_redeemed,
            "pending": invite_created - invite_redeemed,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/audit")
def admin_audit(action: str | None = None, actor: int | None = None,
                page: int = 1, user: User = Depends(get_admin_user),
                session: Session = Depends(get_db)) -> dict:
    """Audit trail viewer (Sprint 07, B4). Admin-only, filters on action or
    actor id, newest first. Every viewer call is itself recorded as an
    ``admin.audit_view`` event."""
    limit = 50
    page = max(1, int(page))  # clamp: page < 1 is meaningless (and page=0
                              # would return nothing rather than the first page)
    rows = AuditEventRepo(session).list(action=action, actor_id=actor,
                                        page=page, limit=limit)
    events = [
        {
            "id": e.id,
            "actor_type": e.actor_type,
            "actor_id": e.actor_id,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "ip": e.ip,
            "user_agent": e.user_agent,
            "meta": e.meta,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]
    log_audit(session, action="admin.audit_view", actor_type="user",
              actor_id=user.id, ip=None, meta={"page": page,
                                               "action": action,
                                               "actor": actor})
    session.commit()
    return {"events": events, "page": page, "limit": limit}


# --- API keys (Sprint 08, Track A2) -------------------------------------------
@router.get("/apikeys")
def admin_list_api_keys(page: int = 1, limit: int = 50,
                        user: User = Depends(get_admin_user),
                        session: Session = Depends(get_db)) -> dict:
    """All API keys across every user, newest first (admin only)."""
    page = max(1, int(page))
    limit = min(max(1, int(limit)), 200)
    repo = ApiKeyRepo(session)
    keys = repo.list_all(page=page, limit=limit)
    items = []
    for key in keys:
        owner = session.get(User, key.user_id)
        item = api_key_out(key)
        item["user_email"] = owner.email if owner else None
        items.append(item)
    return {"items": items, "page": page, "limit": limit,
            "total": len(items)}


@router.post("/apikeys/{key_id}/revoke")
def admin_revoke_api_key(key_id: int,
                         user: User = Depends(get_admin_user),
                         session: Session = Depends(get_db)) -> dict:
    """Revoke any user's API key (admin only)."""
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is not None:
        raise HTTPException(status_code=409, detail="API key already revoked")
    ApiKeyRepo(session).revoke(key)
    log_audit(session, action="admin.apikey.revoke", actor_type="user",
              actor_id=user.id, target_type="api_key", target_id=key.id)
    session.commit()
    return {"status": "revoked", "id": key.id, "key_prefix": key.key_prefix}


@router.patch("/apikeys/{key_id}/limits")
def admin_override_key_limits(
    key_id: int,
    body: ApiKeyQuotaOverride,
    user: User = Depends(get_admin_user),
    session: Session = Depends(get_db),
) -> dict:
    """Override a key's per-day quota and/or per-minute rate (admin only)."""
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    ApiKeyRepo(session).set_limits(key, quota_limit=body.quota_limit,
                                   rate_limit=body.rate_limit)
    log_audit(session, action="admin.apikey.limits", actor_type="user",
              actor_id=user.id, target_type="api_key", target_id=key.id,
              meta={"quota_limit": body.quota_limit,
                    "rate_limit": body.rate_limit})
    session.commit()
    return api_key_out(key)


@router.get("/apikeys/{key_id}/usage")
def admin_key_usage(key_id: int,
                    user: User = Depends(get_admin_user),
                    session: Session = Depends(get_db),
                    days: int = 30) -> dict:
    """Per-day usage rollup for one key + its quota settings (admin only)."""
    key = session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    days = min(max(1, days), 90)
    rows = ApiKeyUsageRepo(session).list_usage(key_id, limit=days)
    owner = session.get(User, key.user_id)
    return {
        "key": api_key_out(key),
        "user_email": owner.email if owner else None,
        "items": [
            {"date": r.usage_date, "requests": r.requests,
             "rate_limited": r.rate_limited}
            for r in rows
        ],
    }
