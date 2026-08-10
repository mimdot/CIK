"""core.cache — caching layer for expensive, deterministic reads (Sprint 06, B1).

Caches match results, opportunity lists, and supervisor lists behind a single
small API. Redis is the preferred store (1-hour TTLs, shared across API
workers); when ``REDIS_URL`` is unset or Redis is unreachable the module
degrades gracefully to a process-local in-memory store so nothing breaks in
dev or single-process deploys.

Keys are namespaced by profile/entity id and versioned so that any data
mutation (a fresh pipeline run, new supervisor data) can invalidate the
relevant keys in one shot.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

log = logging.getLogger("phd_aggregator")

MATCHES_TTL = 3600          # 1 hour
OPPORTUNITIES_TTL = 3600
SUPERVISORS_TTL = 3600

_redis = None
_redis_lock = threading.Lock()
_in_memory: dict[str, tuple[float, str]] = {}
_in_memory_lock = threading.Lock()
_broken = False
_broken_since: float = 0.0
RETRY_INTERVAL = 300  # seconds to wait before retrying a failed connection


def _get_redis():
    """Return a lazily-created Redis client, or None when Redis is off/unused."""
    global _redis, _broken, _broken_since
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    if _redis is None:
        if _broken:
            # Back off and retry periodically instead of staying broken forever.
            if time.monotonic() - _broken_since < RETRY_INTERVAL:
                return None
            _broken = False
        with _redis_lock:
            if _redis is None and not _broken:
                try:
                    import redis
                    client = redis.from_url(url, decode_responses=True,
                                            socket_connect_timeout=0.5,
                                            socket_timeout=1.0)
                    client.ping()
                    _redis = client
                except Exception as exc:  # pragma: no cover - depends on infra
                    log.warning("Redis unavailable — falling back to in-memory "
                                "cache: %s", exc)
                    _broken = True
                    _broken_since = time.monotonic()
                    _redis = None
    return _redis


def _is_healthy(client) -> bool:
    try:
        client.ping()
        return True
    except Exception:
        return False


def _backend() -> str:
    """Which store is active: 'redis' or 'memory'."""
    client = _get_redis()
    return "redis" if client is not None else "memory"


def _redis_get(client, key: str) -> Optional[str]:
    try:
        return client.get(key)
    except Exception:
        return None


def _redis_set(client, key: str, value: str, ttl: int) -> None:
    try:
        client.setex(key, ttl, value)
    except Exception:
        pass


def _redis_delete(client, prefix: str) -> int:
    try:
        keys = list(client.scan_iter(match=f"{prefix}*"))
        if keys:
            client.delete(*keys)
        return len(keys)
    except Exception:
        return 0


# --- generic key/value --------------------------------------------------------
def get(key: str) -> Optional[Any]:
    """Fetch a JSON value by key, or None on miss."""
    client = _get_redis()
    if client is not None:
        raw = _redis_get(client, key)
        if raw is not None:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None
    with _in_memory_lock:
        entry = _in_memory.get(key)
    if entry is None:
        return None
    expires, raw = entry
    if expires < time.monotonic():
        with _in_memory_lock:
            _in_memory.pop(key, None)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set(key: str, value: Any, ttl: int = 3600) -> None:
    """Store ``value`` under ``key`` with a TTL (seconds)."""
    raw = json.dumps(value, ensure_ascii=False)
    client = _get_redis()
    if client is not None:
        _redis_set(client, key, raw, ttl)
        return
    with _in_memory_lock:
        _in_memory[key] = (time.monotonic() + ttl, raw)


def invalidate(prefix: str) -> int:
    """Drop every key starting with ``prefix``; returns number removed."""
    client = _get_redis()
    if client is not None:
        return _redis_delete(client, prefix)
    with _in_memory_lock:
        doomed = [k for k in _in_memory if k.startswith(prefix)]
        for k in doomed:
            _in_memory.pop(k, None)
        return len(doomed)


# --- matches ------------------------------------------------------------------
def match_key(profile_id: int) -> str:
    return f"matches:{profile_id}"


def cache_match_results(profile_id: int, results: list) -> None:
    set(match_key(profile_id), results, ttl=MATCHES_TTL)


def get_cached_matches(profile_id: int) -> Optional[list]:
    return get(match_key(profile_id))


def invalidate_matches(profile_id: Optional[int] = None) -> int:
    return invalidate("matches:") if profile_id is None else invalidate(
        f"matches:{profile_id}")


# --- opportunities ------------------------------------------------------------
def opportunity_list_key() -> str:
    return "opportunities:list"


def cache_opportunity_list(results: list) -> None:
    set(opportunity_list_key(), results, ttl=OPPORTUNITIES_TTL)


def get_cached_opportunity_list() -> Optional[list]:
    return get(opportunity_list_key())


def invalidate_opportunities() -> int:
    return invalidate("opportunities:")


# --- supervisors --------------------------------------------------------------
def supervisor_list_key() -> str:
    return "supervisors:list"


def cache_supervisor_list(results: list) -> None:
    set(supervisor_list_key(), results, ttl=SUPERVISORS_TTL)


def get_cached_supervisor_list() -> Optional[list]:
    return get(supervisor_list_key())


def invalidate_supervisors() -> int:
    return invalidate("supervisors:")
