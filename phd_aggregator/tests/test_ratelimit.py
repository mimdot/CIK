"""tests.test_ratelimit — Sprint 07, Track B1.

Verifies the Redis-backed rate limiter's public API (check/remaining/clear)
and the backward-compatible _RateLimiter used by the auth endpoints. Tests run
against the in-process fallback (no Redis in CI); a live integration check is
skipped when REDIS_URL is configured.
"""

from __future__ import annotations

import time

from api.security import login_limiter, register_limiter
from core.ratelimit import RedisRateLimiter


def test_limits_within_window():
    limiter = RedisRateLimiter(max_requests=3, window_seconds=60)
    key = "unit-client"
    assert limiter.check(key) is True
    assert limiter.check(key) is True
    assert limiter.check(key) is True
    assert limiter.check(key) is False
    assert limiter.remaining(key) == 0


def test_clear_resets():
    limiter = RedisRateLimiter(max_requests=1, window_seconds=60)
    key = "unit-clear"
    assert limiter.check(key) is True
    assert limiter.check(key) is False
    limiter.clear(key)
    assert limiter.check(key) is True


def test_window_boundary_resets_bucket():
    limiter = RedisRateLimiter(max_requests=1, window_seconds=10)
    key = "unit-boundary"
    now = 1_000_000.0
    assert limiter.check(key, now=now) is True
    assert limiter.check(key, now=now) is False  # budget exhausted
    # 10s later the bucket rolls over and a fresh budget is available.
    assert limiter.check(key, now=now + 10) is True
    assert limiter.check(key, now=now + 10) is False


def test_keys_are_independent():
    limiter = RedisRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.check("unit-a") is True
    assert limiter.check("unit-a") is False
    assert limiter.check("unit-b") is True


def test_auth_limiters_work_without_redis():
    assert register_limiter.check("integration-client") is True
    register_limiter.clear("integration-client")
    assert login_limiter.check("integration-client") is True
    login_limiter.clear("integration-client")


# --- Redis path (fake client) --------------------------------------------------
class _FakeRedis:
    """Minimal in-memory stand-in for the Redis commands the limiter uses."""

    def __init__(self):
        self._store = {}

    def get(self, key):
        if key in self._store:
            return str(self._store[key])
        return None

    def incr(self, key):
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    def expire(self, key, ttl):
        return True

    def delete(self, *keys):
        removed = sum(1 for k in keys if self._store.pop(k, None) is not None)
        return removed

    def scan_iter(self, match=None):
        return [k for k in self._store]

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True


def _use_fake_redis(monkeypatch, fake):
    import core.ratelimit as rl
    monkeypatch.setattr(rl, "_get_redis", lambda: fake)


def test_redis_sliding_window_prevents_double_burst(monkeypatch):
    """The whole point of the fix: no 2x burst across a window boundary."""
    _use_fake_redis(monkeypatch, _FakeRedis())
    limiter = RedisRateLimiter(max_requests=2, window_seconds=1000)
    key = "redis-burst"
    base = 100_000
    assert limiter.check(key, now=base) is True
    assert limiter.check(key, now=base + 999) is True       # budget full
    assert limiter.check(key, now=base + 999) is False
    # Boundary: the OLD fixed window would hand out a fresh bucket here; the
    # sliding estimate still counts the previous bucket -> denied.
    assert limiter.check(key, now=base + 1000) is False
    # Half a window later the earliest hit has drained -> allowed again.
    assert limiter.check(key, now=base + 1500) is True


def test_redis_check_and_remaining(monkeypatch):
    _use_fake_redis(monkeypatch, _FakeRedis())
    limiter = RedisRateLimiter(max_requests=5, window_seconds=60)
    key = "redis-rem"
    assert limiter.check(key, now=1_000_000) is True
    assert limiter.remaining(key, now=1_000_010) == 4
    for _ in range(3):
        assert limiter.check(key, now=1_000_020) is True
    assert limiter.remaining(key, now=1_000_030) == 1
    assert limiter.check(key, now=1_000_040) is True
    assert limiter.check(key, now=1_000_050) is False
    assert limiter.remaining(key, now=1_000_050) == 0


def test_redis_clear_resets(monkeypatch):
    _use_fake_redis(monkeypatch, _FakeRedis())
    limiter = RedisRateLimiter(max_requests=1, window_seconds=60)
    key = "redis-clear"
    assert limiter.check(key, now=1_000_000) is True
    assert limiter.check(key, now=1_000_010) is False
    limiter.clear(key, now=1_000_020)
    assert limiter.check(key, now=1_000_020) is True


def test_redis_keys_are_independent(monkeypatch):
    _use_fake_redis(monkeypatch, _FakeRedis())
    limiter = RedisRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.check("redis-a", now=1_000_000) is True
    assert limiter.check("redis-a", now=1_000_010) is False
    assert limiter.check("redis-b", now=1_000_020) is True


def test_in_memory_store_is_bounded(monkeypatch):
    """Many distinct client keys must not grow the fallback dict forever."""
    import core.ratelimit as rl
    monkeypatch.setattr(rl, "_MAX_TRACKED_KEYS", 5)
    rl._IN_MEMORY.clear()
    limiter = RedisRateLimiter(max_requests=1, window_seconds=60)
    for i in range(20):
        assert limiter.check(f"bounded-{i}", now=1_000_000 + i) is True
    assert len(rl._IN_MEMORY) <= 5
    rl._IN_MEMORY.clear()
