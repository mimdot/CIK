"""api.routes.apikeys — developer API-key lifecycle (Sprint 08, Track A2).

A developer manages their *own* keys with a user JWT. The raw key
(``cik_`` + 40 hex chars) is generated here, hashed with SHA-256 before it
hits the DB (``api.security.hash_token``), and returned to the caller exactly
once at create/rotate time — it is never stored or logged in the clear.

Routes:
- ``GET    /api/v1/apikeys``        list own keys (prefix, scopes, status)
- ``POST   /api/v1/apikeys``        create → returns raw key once
- ``PATCH  /api/v1/apikeys/{id}``   rename / change scopes
- ``DELETE /api/v1/apikeys/{id}``   soft-revoke
- ``POST   /api/v1/apikeys/{id}/rotate`` issue new key, revoke the old one
- ``GET    /api/v1/apikeys/{id}/usage`` per-day counts + quota
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas import ApiKeyCreate, ApiKeyUpdate
from api.scopes import DEFAULT_SCOPES
from api.security import hash_token, log_audit
from api.serializers import api_key_out
from db.models import ApiKey, User
from db.repositories import ApiKeyRepo, ApiKeyUsageRepo

router = APIRouter(prefix="/api/v1/apikeys", tags=["apikeys"])

_RAW_KEY_PREFIX = "cik_"


def generate_raw_key() -> str:
    """A fresh raw API key: ``cik_`` + 40 hex chars (192 bits of entropy)."""
    return f"{_RAW_KEY_PREFIX}{secrets.token_hex(20)}"


def key_prefix_of(raw_key: str) -> str:
    """The first 12 chars, used as a display-only badge for the key."""
    return raw_key[:12]


def _get_own_key(key_id: int, user: User, session: Session) -> ApiKey:
    key = ApiKeyRepo(session).get_by_id(key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    return key


def _key_out_with_raw(key: ApiKey, raw_key: str) -> dict:
    """ApiKey serializer plus the one-time raw key."""
    out = api_key_out(key)
    out["raw_key"] = raw_key
    return out


@router.get("")
def list_own_keys(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """List the caller's keys — hashes are never exposed, only prefixes."""
    keys = ApiKeyRepo(session).list_for_user(user.id)
    return {"items": [api_key_out(k) for k in keys], "total": len(keys)}


@router.post("", status_code=201)
def create_key(
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """Create a key; the raw key is returned in this response only."""
    raw_key = generate_raw_key()
    scopes = list(body.scopes) if body.scopes is not None \
        else list(DEFAULT_SCOPES)
    repo = ApiKeyRepo(session)
    key = repo.create(user_id=user.id, name=body.name,
                      key_hash=hash_token(raw_key),
                      key_prefix=key_prefix_of(raw_key),
                      scopes=scopes, expires_at=body.expires_at)
    log_audit(session, action="apikey.create", actor_type="user",
              actor_id=user.id, target_type="api_key", target_id=key.id,
              meta={"name": body.name, "scopes": scopes})
    session.commit()
    return _key_out_with_raw(key, raw_key)


@router.patch("/{key_id}")
def update_key(
    key_id: int,
    body: ApiKeyUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """Rename a key and/or change its scopes."""
    key = _get_own_key(key_id, user, session)
    if body.name is not None:
        key.name = body.name
    if body.scopes is not None:
        import json
        key.scopes = json.dumps(body.scopes, ensure_ascii=False)
    log_audit(session, action="apikey.update", actor_type="user",
              actor_id=user.id, target_type="api_key", target_id=key.id,
              meta={"name": body.name, "scopes": body.scopes})
    session.commit()
    return api_key_out(key)


@router.delete("/{key_id}")
def revoke_key(
    key_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """Soft-revoke a key: calls with it fail with 401 from now on."""
    key = _get_own_key(key_id, user, session)
    if key.revoked_at is not None:
        raise HTTPException(status_code=409, detail="API key already revoked")
    ApiKeyRepo(session).revoke(key)
    log_audit(session, action="apikey.revoke", actor_type="user",
              actor_id=user.id, target_type="api_key", target_id=key.id)
    session.commit()
    return {"status": "revoked", "id": key.id, "key_prefix": key.key_prefix}


@router.post("/{key_id}/rotate")
def rotate_key(
    key_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    """Revoke the existing key and issue a fresh one with the same settings.

    The new raw key is returned once. The old key is soft-revoked so any
    in-flight consumers stop working immediately.
    """
    old = _get_own_key(key_id, user, session)
    import json
    scopes = json.loads(old.scopes) if old.scopes else list(DEFAULT_SCOPES)
    raw_key = generate_raw_key()
    repo = ApiKeyRepo(session)
    repo.revoke(old)
    new = repo.create(user_id=user.id, name=old.name,
                      key_hash=hash_token(raw_key),
                      key_prefix=key_prefix_of(raw_key),
                      scopes=scopes, quota_limit=old.quota_limit,
                      rate_limit=old.rate_limit, expires_at=old.expires_at)
    log_audit(session, action="apikey.rotate", actor_type="user",
              actor_id=user.id, target_type="api_key", target_id=new.id,
              meta={"old_key_id": old.id, "new_key_id": new.id})
    session.commit()
    return _key_out_with_raw(new, raw_key)


@router.get("/{key_id}/usage")
def key_usage(
    key_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    days: int = 30,
) -> dict:
    """Per-day request counts (last ``days``, default 30) + quota settings."""
    key = _get_own_key(key_id, user, session)
    days = min(max(1, days), 90)
    rows = ApiKeyUsageRepo(session).list_usage(key_id, limit=days)
    usage = [
        {"date": r.usage_date, "requests": r.requests,
         "rate_limited": r.rate_limited}
        for r in rows
    ]
    return {
        "key_id": key.id,
        "quota_limit": key.quota_limit,
        "rate_limit": key.rate_limit,
        "items": usage,
        "total": len(usage),
    }
