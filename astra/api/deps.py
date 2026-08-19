"""api.deps — FastAPI dependency-injection glue (Sprint 04, A1/C2).

``get_db`` yields a request-scoped SQLAlchemy session over the default engine
(tests override it with an in-memory session). ``get_current_user`` resolves
the authenticated :class:`User` from the Bearer token (API clients) or, as a
fallback, from the httpOnly ``cik_token`` cookie (browsers) and is attached to
every endpoint that must require auth (profile / matches / bookmarks). The
``get_active_profile_*`` helpers scope the active profile to the current user.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.scopes import DEFAULT_SCOPES, user_jwt_scopes
from api.security import decode_access_token, hash_token
from core.profile_schema import UserProfile
from core.ratelimit import RedisRateLimiter, api_key_meter
from db.init import create_engine_and_base, init_db, resolve_db_url
from db.models import ApiKey, User, UserProfileRow
from db.repositories import ApiKeyRepo, ProfileRepo, UserRepo

_http_bearer = HTTPBearer(auto_error=False)

# Name of the httpOnly session cookie set by ``POST /api/auth/login``. Kept in
# deps (not api.routes.auth) because ``get_current_user`` needs it and importing
# the auth router here would be a circular import.
COOKIE_NAME = "cik_token"

_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    """Create the SQLAlchemy engine once and reuse it (thread-safe singleton).

    Uses ``DATABASE_URL`` (env) when set — see :func:`db.init.resolve_db_url`.
    For PostgreSQL the engine is created with a bounded ``QueuePool``
    (pool_size=5, max_overflow=10) so a misbehaving client cannot exhaust
    server connections; see :func:`db.init.create_engine_and_base`."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = init_db(resolve_db_url())
    return _engine


def get_db() -> Iterator[Session]:
    """Yield a SQLAlchemy session for dependency injection."""
    engine = _get_engine()
    with Session(engine) as session:
        yield session


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_http_bearer),
    session: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Bearer token or the httpOnly
    session cookie, or raise 401.

    Bearer tokens take precedence and, when present, are authoritative: a
    request carrying an ``Authorization: Bearer`` header is treated purely as a
    Bearer-authenticated client (invalid tokens fail rather than silently
    falling back to the cookie). Only when no Bearer header is sent do we read
    the ``cik_token`` cookie, so CSRF protection (which exempts Bearer
    requests) stays sound for browser sessions.
    """
    token: Optional[str] = None
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _unauthorized()
    user_id = decode_access_token(token)
    if user_id is None:
        raise _unauthorized()
    user = UserRepo(session).get_by_id(user_id)
    if user is None:
        raise _unauthorized()
    return user


def get_active_profile_row(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Optional[UserProfileRow]:
    """The authenticated user's active profile row (scoped), or None."""
    return ProfileRepo(session).get_active(user_id=user.id)


def get_active_profile(
    row: Optional[UserProfileRow] = Depends(get_active_profile_row),
) -> Optional[UserProfile]:
    """The authenticated user's active profile as a validated UserProfile."""
    return UserProfile(**row.to_profile()) if row else None


def get_profile_or_404(
    row: Optional[UserProfileRow] = Depends(get_active_profile_row),
) -> UserProfileRow:
    """Like get_active_profile_row, but raises 404 when no profile exists."""
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No active profile — build one first")
    return row


# ---------------------------------------------------------------------------
# Public API principals (Sprint 08, Track B1)
# ---------------------------------------------------------------------------
# Default per-minute rate for an API key (overridable per key via rate_limit).
API_KEY_RATE_DEFAULT = 60
# Global per-IP guardrail for /api/v1 (a single consumer cannot saturate the box).
API_V1_IP_RATE = int(__import__("os").environ.get("API_V1_IP_RATE", "600"))

_KEY_LIMITERS: dict[int, RedisRateLimiter] = {}
_KEY_LIMITERS_LOCK = threading.Lock()
_IP_LIMITER = RedisRateLimiter(API_V1_IP_RATE, 60, prefix="v1_ip")

# Throttled last_used_at bookkeeping (no write per request).
_TOUCH: dict[int, float] = {}
_TOUCH_LOCK = threading.Lock()
_TOUCH_TTL = 60.0
_TOUCH_MAX_KEYS = 10_000


class ApiPrincipal:
    """An authenticated /api/v1 caller: a user (JWT) or a scoped API key.

    ``scopes`` is the effective permission set for this request; ``key_id``
    is set only for API-key callers (used for rate/quota enforcement).
    """

    __slots__ = ("user_id", "role", "scopes", "key_id")

    def __init__(self, user_id: int, role: str = "user",
                 scopes: Optional[tuple] = None,
                 key_id: Optional[int] = None):
        self.user_id = user_id
        self.role = role
        self.scopes = frozenset(scopes or ())
        self.key_id = key_id

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def _decode_scopes(value: Optional[str]) -> tuple:
    if not value:
        return DEFAULT_SCOPES
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return DEFAULT_SCOPES
    return tuple(parsed) if isinstance(parsed, list) else DEFAULT_SCOPES


def _touch_last_used_throttled(key: ApiKey, session: Session) -> None:
    """Best-effort last_used_at write, at most once a minute per key.

    Uses Redis SET NX as a cross-worker throttle; the in-process fallback is
    a bounded monotonic-time dict. A failed touch is never fatal.
    """
    from core.cache import _get_redis
    client = _get_redis()
    now = time.monotonic()
    if client is not None:
        try:
            if client.set(f"lastused:apikey:{key.id}", "1",
                          nx=True, ex=int(_TOUCH_TTL)):
                ApiKeyRepo(session).touch_last_used(key)
                session.commit()
            return
        except Exception:
            pass
    with _TOUCH_LOCK:
        if now - _TOUCH.get(key.id, 0.0) >= _TOUCH_TTL:
            _TOUCH[key.id] = now
            if len(_TOUCH) > _TOUCH_MAX_KEYS:
                _TOUCH.pop(next(iter(_TOUCH)), None)
            ApiKeyRepo(session).touch_last_used(key)
            session.commit()


def _principal_from_api_key(token: str, session: Session) -> ApiPrincipal:
    key = ApiKeyRepo(session).get_by_hash(hash_token(token))
    if key is None:
        raise _unauthorized()
    now = datetime.now(timezone.utc)
    expires = key.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="API key has been revoked")
    if expires is not None and expires <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="API key has expired")
    _touch_last_used_throttled(key, session)
    return ApiPrincipal(user_id=key.user_id, role="apikey",
                        scopes=_decode_scopes(key.scopes), key_id=key.id)


def _principal_from_jwt(token: str, session: Session) -> ApiPrincipal:
    user_id = decode_access_token(token)
    if user_id is None:
        raise _unauthorized()
    user = UserRepo(session).get_by_id(user_id)
    if user is None:
        raise _unauthorized()
    return ApiPrincipal(user_id=user.id, role=user.role,
                        scopes=user_jwt_scopes(user.role))


def get_api_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_http_bearer),
    session: Session = Depends(get_db),
) -> ApiPrincipal:
    """Resolve a Bearer JWT or Bearer API key into an :class:`ApiPrincipal`.

    Tokens beginning with ``cik_`` are treated as API keys (SHA-256 lookup,
    revoked/expired rejected); anything else is decoded as a user JWT. The
    public ``/api/v1`` routes use this + :func:`require_scope`; the internal
    routes keep using :func:`get_current_user` untouched.
    """
    if credentials is None:
        raise _unauthorized()
    token = credentials.credentials
    if token.startswith("cik_"):
        return _principal_from_api_key(token, session)
    return _principal_from_jwt(token, session)


def require_scope(scope: str):
    """Dependency factory: fail 403 unless the principal holds ``scope``."""
    def dependency(principal: ApiPrincipal = Depends(get_api_principal),
                   ) -> ApiPrincipal:
        if not principal.has_scope(scope):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Missing required scope: {scope}")
        return principal
    dependency.__name__ = f"require_scope_{scope.replace(':', '_')}"
    return dependency


# ---------------------------------------------------------------------------
# Public API limits + metering (Sprint 08, Track B2)
# ---------------------------------------------------------------------------
def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limiter_for(key_id: int, rate: int) -> RedisRateLimiter:
    """A per-key sliding-window limiter, cached (bounded) per key id."""
    with _KEY_LIMITERS_LOCK:
        lim = _KEY_LIMITERS.get(key_id)
        if lim is not None and lim.max_requests == rate:
            return lim
        lim = RedisRateLimiter(rate, 60, prefix="apikey_rate")
        _KEY_LIMITERS[key_id] = lim
        if len(_KEY_LIMITERS) > 10_000:
            _KEY_LIMITERS.pop(next(iter(_KEY_LIMITERS)), None)
        return lim


def _seconds_until_next_minute(now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    return int(60 - (now % 60))


def _seconds_until_midnight(now: Optional[float] = None) -> int:
    import datetime as _dt
    now = datetime.now(timezone.utc) if now is None else \
        datetime.fromtimestamp(time.time() if now is None else now,
                               timezone.utc)
    nxt = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) \
        + _dt.timedelta(days=1)
    return max(1, int((nxt - now).total_seconds()))


def _rate_headers(limit: int, remaining: int,
                  reset_seconds: int) -> dict[str, str]:
    reset = int(time.time()) + reset_seconds
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(reset),
    }


def enforce_api_limits(
    request: Request,
    response: Response,
    principal: ApiPrincipal = Depends(get_api_principal),
    session: Session = Depends(get_db),
) -> ApiPrincipal:
    """Per-key rate + daily-quota limits and the global per-IP guardrail.

    Counts every /api/v1 request into the meter (so usage reports real
    numbers), then enforces: per-key sliding window (default 60/min, or the
    key's ``rate_limit`` override) → 429; per-day quota (``quota_limit``,
    unlimited by default) → 429 with ``Retry-After``; plus a coarse per-IP
    cap for the whole public API.
    """
    if not _IP_LIMITER.check(f"ip:{_client_ip(request)}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests (per-IP limit)",
            headers={"Retry-After": "60"})
    if principal.key_id is None:
        return principal
    key = ApiKeyRepo(session).get_by_id(principal.key_id)
    if key is None:  # pragma: no cover - principal was just validated
        return principal

    requests = api_key_meter.count_request(key.id)  # meter every attempt once
    rate = key.rate_limit or API_KEY_RATE_DEFAULT
    limiter = _limiter_for(key.id, rate)
    rate_key = f"key:{key.id}"
    allowed = limiter.check(rate_key)
    remaining = limiter.remaining(rate_key)
    headers = _rate_headers(rate, remaining, _seconds_until_next_minute())
    if not allowed:
        api_key_meter.count_rate_limited(key.id)
        headers["Retry-After"] = str(_seconds_until_next_minute())
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Rate limit exceeded", headers=headers)

    # Daily quota: a key with quota_limit=N may make N requests per UTC day;
    # the request that pushes the total past N is rejected.
    if key.quota_limit is not None and requests > key.quota_limit:
        api_key_meter.count_rate_limited(key.id)
        headers["Retry-After"] = str(_seconds_until_midnight())
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Daily quota exceeded", headers=headers)

    for name, value in headers.items():
        response.headers[name] = value
    return principal
