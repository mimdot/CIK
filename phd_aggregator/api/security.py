"""api.security — bcrypt password hashing + JWT token helpers (Sprint 04,
Track C1).

Passwords are hashed with bcrypt (never stored in plaintext); sessions use
signed HS256 JWTs issued by :func:`create_access_token`. The signing key comes
from the ``CIK_SECRET_KEY`` environment variable with a dev fallback (overriden
in production deployments).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

import bcrypt
from jose import JWTError, jwt

SECRET_KEY = os.environ.get("CIK_SECRET_KEY", "")
if not SECRET_KEY:
    import warnings
    warnings.warn(
        "CIK_SECRET_KEY not set — tokens are signed with an insecure "
        "dev key. Set the env var before any deployment.",
        stacklevel=2,
    )
    SECRET_KEY = "dev-insecure-key-do-not-deploy"
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 60 * 60  # 1 hour


from core.ratelimit import RedisRateLimiter

class _RateLimiter(RedisRateLimiter):
    """Per-client rate limiter (Sprint 07, B1): Redis-backed when available,
    in-process fallback otherwise. Public API is unchanged (check/remaining/
    clear), so existing callers keep working. Limits are now shared across
    uvicorn workers instead of per-process.
    """

    def __init__(self, max_requests: int, window_seconds: float,
                 prefix: str = "auth"):
        super().__init__(max_requests, window_seconds, prefix)


register_limiter = _RateLimiter(max_requests=3, window_seconds=60 * 60,
                                prefix="register")                     # 3/hour
login_limiter = _RateLimiter(max_requests=5, window_seconds=60,
                             prefix="login")                           # 5/min
reset_limiter = _RateLimiter(max_requests=5, window_seconds=60 * 60,
                             prefix="reset")                           # 5/hour
verify_limiter = _RateLimiter(max_requests=5, window_seconds=60 * 60,
                              prefix="verify")                         # 5/hour


def hash_password(password: str) -> str:
    """bcrypt-hash a plaintext password (salt embedded in the hash)."""
    return bcrypt.hashpw(password.encode("utf-8"),
                         bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time-ish bcrypt check; False on any malformed hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    """Issue a signed HS256 JWT carrying the user id as ``sub``."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    """Return the user id embedded in a valid token, or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# HMAC signing (Sprint 07, A4) — single-use tokens (email unsubscribe links)
# ---------------------------------------------------------------------------
def hmac_sign(value: str, ttl_seconds: int = 60 * 60 * 24 * 30) -> str:
    """Sign ``value`` with the app secret, embedding the current time bucket.

    Returns ``"{ttl}.{value}.{signature}"``. ``ttl_seconds`` bounds how long
    the token remains valid (default 30 days).
    """
    expires = int(time.time()) + ttl_seconds
    payload = f"{expires}.{value}"
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return f"{ttl_seconds}.{expires}.{value}.{sig}"


def hmac_verify(token: str) -> Optional[str]:
    """Validate a token produced by :func:`hmac_sign` and return the payload
    value, or None when the token is malformed, tampered, or expired."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    _ttl, expires, value, sig = parts
    try:
        if int(expires) < int(time.time()):
            return None
    except ValueError:
        return None
    payload = f"{expires}.{value}"
    expected = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    return value


# ---------------------------------------------------------------------------
# Single-use tokens (Sprint 07, B2) — password reset / email verification
# ---------------------------------------------------------------------------
def generate_secure_token() -> str:
    """A 32-byte URL-safe random token shown to the user once."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hash of a token — only the hash is persisted (never plaintext)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Audit log helper (Sprint 07, B4) — write an immutable action row
# ---------------------------------------------------------------------------
def log_audit(session, *, action: str,
              actor_type: str = "user", actor_id: Optional[int] = None,
              target_type: Optional[str] = None,
              target_id: Optional[int] = None,
              ip: Optional[str] = None,
              user_agent: Optional[str] = None,
              meta: Optional[dict] = None) -> None:
    """Append an audit_events row via AuditEventRepo. Never raises.

    Callers commit the session; failures are logged so audit recording cannot
    take an endpoint down.
    """
    try:
        from db.repositories import AuditEventRepo
        AuditEventRepo(session).record(
            actor_type=actor_type, actor_id=actor_id, action=action,
            target_type=target_type, target_id=target_id, ip=ip,
            user_agent=user_agent, meta=meta)
    except Exception:
        import logging
        logging.getLogger("phd_aggregator").exception(
            "audit log write failed for action=%s", action)
