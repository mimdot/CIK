"""core.ratelimit — Redis-backed rolling-window rate limiter (Sprint 07, B1).

The first version used a per-window-bucket counter (``INCR`` + ``EXPIRE``), but
a fixed window lets a client burst TWICE the limit across a boundary (5 tries
at 20:59:59 + 5 more at 21:00:01 = 10 in two minutes). This module keeps the
same public API — ``check/remaining/clear`` — and replaces the fixed window
with the standard two-bucket weighted sliding-window estimate:

    estimate = prev_bucket * (1 - frac) + current_bucket

where ``frac`` is how far into the current bucket the request lands, so a hit
at the *start* of a window still pays for what happened at the *end* of the
previous one. No more 2x burst.

The in-process fallback (no Redis) is a true sliding window over per-request
timestamps and additionally bounds its own memory: at most
``MAX_TRACKED_KEYS`` distinct client keys are kept, oldest-inserted-first, so a
many-client attack cannot grow the dict without limit.
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from core.cache import _get_redis

_IN_MEMORY: dict[str, dict] = {}
_IN_MEMORY_LOCK = threading.Lock()
_MAX_TRACKED_KEYS = 10_000  # cap on distinct client keys (FIFO eviction)


def _memory_evict() -> None:
    """Drop the oldest-inserted key when over the bound (no unbounded growth).

    Python dicts preserve insertion order, so ``next(iter(_IN_MEMORY))`` is the
    earliest key we have seen — FIFO eviction is deterministic and cheap.
    """
    while len(_IN_MEMORY) > _MAX_TRACKED_KEYS:
        _IN_MEMORY.pop(next(iter(_IN_MEMORY)), None)


class RedisRateLimiter:
    """Sliding-window rate limiter shared across API workers via Redis.

    ``max_requests`` per ``window_seconds`` per client ``key``. Falls back to
    a process-local store when Redis is unreachable/unconfigured, so a Redis
    outage degrades limits but never breaks the API.
    """

    def __init__(self, max_requests: int, window_seconds: float,
                 prefix: str = "rate"):
        self.max_requests = max_requests
        self.window_seconds = int(window_seconds)
        self.prefix = prefix

    # ---- Redis backend ------------------------------------------------------
    def _bucket(self, key: str, bucket_index: int) -> str:
        """The Redis key for a window: rate:{prefix}:{key}:{bucket_index}."""
        return f"rate:{self.prefix}:{key}:{bucket_index}"

    def _window_state(self, key: str, now: float,
                      client) -> Optional[tuple[int, int, float]]:
        """(prev_count, current_count, frac) for the sliding-window estimate,
        or None when the window buckets cannot be read (Redis error).
        ``frac`` is how far into the CURRENT bucket the request sits (0..1);
        the PREVIOUS bucket is discounted by ``(1 - frac)``."""
        ts = int(now)
        cur_ts = ts // self.window_seconds
        prev_ts = cur_ts - 1
        frac = (ts - cur_ts * self.window_seconds) / self.window_seconds
        prev = client.get(self._bucket(key, prev_ts))
        cur = client.get(self._bucket(key, cur_ts))
        prev_count = int(prev) if prev is not None else 0
        cur_count = int(cur) if cur is not None else 0
        return prev_count, cur_count, frac

    @staticmethod
    def _estimate(prev_count: int, cur_count: int, frac: float) -> float:
        """Weighted sliding-window estimate of hits in the last window."""
        return prev_count * (1 - frac) + cur_count

    def _redis_check(self, key: str, now: float) -> Optional[bool]:
        """Sliding-window check via Redis; None on error (caller falls back)."""
        client = _get_redis()
        if client is None:
            return None
        try:
            state = self._window_state(key, now, client)
        except Exception:
            return None
        if state is None:
            return None
        prev_count, cur_count, frac = state
        estimated = self._estimate(prev_count, cur_count, frac)
        if estimated + 1 > self.max_requests:
            return False
        cur_ts = int(now) // self.window_seconds
        bucket = self._bucket(key, cur_ts)
        try:
            n = client.incr(bucket)
            if n == 1:
                client.expire(bucket, self.window_seconds * 2)
        except Exception:
            return None
        return True

    def _redis_clear(self, key: Optional[str], now: float) -> None:
        client = _get_redis()
        if client is None:
            return
        try:
            if key is None:
                prefix = f"rate:{self.prefix}:"
                for k in client.scan_iter(match=f"{prefix}*"):
                    client.delete(k)
            else:
                cur_ts = int(now) // self.window_seconds
                client.delete(self._bucket(key, cur_ts))
                client.delete(self._bucket(key, cur_ts - 1))
        except Exception:
            pass

    # ---- in-memory fallback --------------------------------------------------
    def _memory_key(self, key: str) -> str:
        """Namespace the in-memory bucket by prefix so distinct limiters do not
        share counters (register vs login must be independent)."""
        return f"{self.prefix}:{key}"

    def _memory_check(self, key: str, now: float) -> bool:
        key = self._memory_key(key)
        with _IN_MEMORY_LOCK:
            entry = _IN_MEMORY.setdefault(key, {"hits": []})
            if len(_IN_MEMORY) > _MAX_TRACKED_KEYS:
                _memory_evict()
            cutoff = now - self.window_seconds
            hits = [t for t in entry["hits"] if t > cutoff]
            if len(hits) >= self.max_requests:
                entry["hits"] = hits
                return False
            hits.append(now)
            entry["hits"] = hits
            return True

    # ---- public API ----------------------------------------------------------
    def check(self, key: str, now: Optional[float] = None) -> bool:
        """True when the request fits within the sliding window, else False."""
        now = time.time() if now is None else now
        redis_result = self._redis_check(key, now)
        if redis_result is not None:
            return redis_result
        return self._memory_check(key, now)

    def remaining(self, key: str, now: Optional[float] = None) -> int:
        """Hits the client can still make this window (best effort)."""
        now = time.time() if now is None else now
        client = _get_redis()
        if client is not None:
            try:
                state = self._window_state(key, now, client)
                if state is not None:
                    prev_count, cur_count, frac = state
                    estimated = self._estimate(prev_count, cur_count, frac)
                    return max(0, self.max_requests - int(math.ceil(estimated)))
            except Exception:
                pass
        mkey = self._memory_key(key)
        with _IN_MEMORY_LOCK:
            cutoff = now - self.window_seconds
            hits = [t for t in _IN_MEMORY.get(mkey, {}).get("hits", [])
                    if t > cutoff]
            return max(0, self.max_requests - len(hits))

    def clear(self, key: Optional[str] = None,
              now: Optional[float] = None) -> None:
        """Drop counters for one key (or all keys when ``key`` is None).

        ``now`` is the reference clock for choosing which window buckets to
        delete (defaults to the wall clock); tests use it to clear the exact
        window they were driving with ``check(..., now=...)``.
        """
        now = time.time() if now is None else now
        self._redis_clear(key, now)
        with _IN_MEMORY_LOCK:
            if key is None:
                _IN_MEMORY.clear()
            else:
                _IN_MEMORY.pop(self._memory_key(key), None)


# ---------------------------------------------------------------------------
# Per-key API metering + daily quota (Sprint 08, Track B2)
# ---------------------------------------------------------------------------
class ApiKeyMeter:
    """Per-key, per-UTC-day request counters plus daily-quota enforcement.

    Counters live in Redis (``meter:apikey:{key_id}:{YYYY-MM-DD}`` for
    requests, ``ratelimited:apikey:{key_id}:{YYYY-MM-DD}`` for 429s) with a
    48h TTL so rollups can persist them before they expire; when Redis is
    unavailable a bounded in-memory fallback is used. A nightly rollup
    (:func:`core.tasks.rollup_api_key_usage`) copies them into
    ``api_key_usage`` rows for charts and admin views.

    Quota semantics: a request is counted *before* the limit check so usage
    reports real numbers; ``check_quota`` returns ``(requests, remaining)``
    and a caller that observes ``remaining == 0`` replies 429.
    """

    _MEMORY: dict = {}
    _MEMORY_LOCK = threading.Lock()
    _MAX_KEYS = 10_000

    def __init__(self, prefix: str = "apikey"):
        self.prefix = prefix

    # ---- key helpers --------------------------------------------------------
    def _day(self, now: Optional[float] = None) -> str:
        ts = time.time() if now is None else now
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")

    def _req_key(self, key_id: int, day: str) -> str:
        return f"meter:{self.prefix}:{key_id}:{day}"

    def _rl_key(self, key_id: int, day: str) -> str:
        return f"ratelimited:{self.prefix}:{key_id}:{day}"

    # ---- Redis backend ------------------------------------------------------
    def _redis_incr(self, key: str) -> Optional[int]:
        client = _get_redis()
        if client is None:
            return None
        try:
            n = client.incr(key)
            if n == 1:
                client.expire(key, 48 * 3600)
            return int(n)
        except Exception:
            return None

    def _redis_get(self, key: str) -> Optional[int]:
        client = _get_redis()
        if client is None:
            return None
        try:
            v = client.get(key)
            return int(v) if v is not None else 0
        except Exception:
            return None

    # ---- in-memory fallback -------------------------------------------------
    def _mem_incr(self, key_id: int, day: str, rl: bool) -> int:
        with self._MEMORY_LOCK:
            if len(self._MEMORY) > self._MAX_KEYS:
                self._MEMORY.pop(next(iter(self._MEMORY)), None)
            bucket = self._MEMORY.setdefault(
                key_id, {day: {"requests": 0, "rate_limited": 0}})
            if day not in bucket:
                bucket.clear()
                bucket[day] = {"requests": 0, "rate_limited": 0}
            bucket[day]["rate_limited" if rl else "requests"] += 1
            return bucket[day]["rate_limited" if rl else "requests"]

    def _mem_get(self, key_id: int, day: str, rl: bool) -> int:
        with self._MEMORY_LOCK:
            return self._MEMORY.get(key_id, {}).get(
                day, {}).get("rate_limited" if rl else "requests", 0)

    # ---- public API ---------------------------------------------------------
    def count_request(self, key_id: int, now: Optional[float] = None) -> int:
        """Count one API request; returns the day's running total."""
        day = self._day(now)
        n = self._redis_incr(self._req_key(key_id, day))
        return n if n is not None else self._mem_incr(key_id, day, rl=False)

    def count_rate_limited(self, key_id: int,
                           now: Optional[float] = None) -> int:
        """Count one rejected request (rate limit or quota → 429)."""
        day = self._day(now)
        n = self._redis_incr(self._rl_key(key_id, day))
        return n if n is not None else self._mem_incr(key_id, day, rl=True)

    def check_quota(self, key_id: int, quota_limit: Optional[int],
                    now: Optional[float] = None) -> tuple[int, Optional[int]]:
        """Count a request and return ``(requests, remaining)``.

        ``remaining`` is None when the key has no daily cap (unlimited). A
        caller should reply 429 when ``remaining == 0``.
        """
        day = self._day(now)
        requests = self.count_request(key_id, now)
        if quota_limit is None:
            return requests, None
        return requests, max(0, quota_limit - requests)

    def snapshot(self, key_id: int, day: Optional[str] = None,
                 now: Optional[float] = None) -> tuple[int, int]:
        """Counters for ``day`` (default today) without mutating them."""
        day = day or self._day(now)
        r = self._redis_get(self._req_key(key_id, day))
        rl = self._redis_get(self._rl_key(key_id, day))
        if r is not None and rl is not None:
            return r, rl
        return (self._mem_get(key_id, day, rl=False),
                self._mem_get(key_id, day, rl=True))

    def active_keys(self, now: Optional[float] = None) -> list[tuple[int, str]]:
        """``(key_id, day)`` pairs that have counters to roll up."""
        day = self._day(now)
        client = _get_redis()
        if client is not None:
            try:
                pairs = []
                pattern = f"meter:{self.prefix}:*"
                for k in client.scan_iter(match=pattern):
                    rest = k[len(f"meter:{self.prefix}:"):]
                    key_id_s, key_day = rest.rsplit(":", 1)
                    pairs.append((int(key_id_s), key_day))
                return pairs
            except Exception:
                pass
        with self._MEMORY_LOCK:
            return [(kid, d) for kid, days in self._MEMORY.items()
                    for d in days]

    def clear(self, key_id: Optional[int] = None,
              now: Optional[float] = None) -> None:
        """Drop counters for one key (or all keys). Used by tests / rotation."""
        day = self._day(now)
        client = _get_redis()
        if client is not None:
            try:
                if key_id is None:
                    for k in client.scan_iter(match=f"meter:{self.prefix}:*"):
                        client.delete(k)
                    for k in client.scan_iter(match=f"ratelimited:{self.prefix}:*"):
                        client.delete(k)
                else:
                    client.delete(self._req_key(key_id, day))
                    client.delete(self._rl_key(key_id, day))
            except Exception:
                pass
        with self._MEMORY_LOCK:
            if key_id is None:
                self._MEMORY.clear()
            else:
                self._MEMORY.pop(key_id, None)


# Shared meter for API-key metering across the app (B2).
api_key_meter = ApiKeyMeter()