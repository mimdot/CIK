"""core.cancel — cooperative cancellation for long-running jobs (Phase 2A).

The old ``cancel_job`` could only cancel a job that had **not started**: once a
crawl was underway, pressing Cancel marked the record and then quietly let the
crawl run to completion, throwing its results away at the end. What the user
wants is the opposite — stop promptly, and *keep* whatever was already found.

The mechanism is a token the pipeline checks at safe points (between sources,
and before each stage). Nothing is killed mid-flight: no thread is terminated,
no process signalled, no HTTP connection ripped away. A source already in
flight finishes its current request and its records are kept; sources not yet
started are simply never started.

Two backends, one interface:

* **in-process** (no Redis) — a ``threading.Event``.
* **rq** — a short-lived Redis key, so the API process can cancel a job running
  in a *different* worker process.

``NullToken`` is the do-nothing default, so every call site can hold a token
unconditionally without branching.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Protocol

log = logging.getLogger("core.cancel")

# How long a cancellation flag lives in Redis. Comfortably longer than any
# sane run, short enough that a stale flag cannot cancel a future job that
# happens to reuse the id.
CANCEL_TTL_S = 6 * 3600

_REDIS_PREFIX = "astra:cancel:"


class CancelToken(Protocol):
    """Anything the pipeline can poll to ask "should I stop?"."""

    def is_cancelled(self) -> bool: ...


class NullToken:
    """Never cancels. The default, so call sites need no ``if token`` dance."""

    def is_cancelled(self) -> bool:
        return False


class EventToken:
    """In-process token backed by a ``threading.Event``."""

    def __init__(self, event: Optional[threading.Event] = None) -> None:
        self.event = event or threading.Event()

    def cancel(self) -> None:
        self.event.set()

    def is_cancelled(self) -> bool:
        return self.event.is_set()


class RedisToken:
    """Cross-process token: a key in Redis set by whoever calls cancel.

    Polled from a worker, so it caches a positive result — once cancelled,
    always cancelled — and never raises: a Redis hiccup must not abort a run
    that is otherwise healthy.
    """

    def __init__(self, client, job_id: str) -> None:
        self.client = client
        self.key = f"{_REDIS_PREFIX}{job_id}"
        self._cancelled = False

    def is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        try:
            if self.client.exists(self.key):
                self._cancelled = True
        except Exception as exc:  # pragma: no cover - depends on Redis
            log.debug("cancel check failed (%s) — continuing", exc)
        return self._cancelled


# --- in-process registry -------------------------------------------------------
_tokens: dict[str, EventToken] = {}
_tokens_lock = threading.Lock()


def register(job_id: str) -> EventToken:
    """Create and store the token for a job about to run in this process."""
    token = EventToken()
    with _tokens_lock:
        _tokens[job_id] = token
    return token


def get(job_id: str) -> Optional[EventToken]:
    with _tokens_lock:
        return _tokens.get(job_id)


def release(job_id: str) -> None:
    """Forget a finished job's token (called from the run's finally block)."""
    with _tokens_lock:
        _tokens.pop(job_id, None)


def request_cancel(job_id: str) -> bool:
    """Ask an in-process job to stop. True if a live token was found."""
    token = get(job_id)
    if token is None:
        return False
    token.cancel()
    log.info("cancellation requested for job %s", job_id)
    return True


def request_cancel_redis(client, job_id: str) -> bool:
    """Ask a job running in an rq worker to stop, via a Redis flag."""
    try:
        client.setex(f"{_REDIS_PREFIX}{job_id}", CANCEL_TTL_S, "1")
        log.info("cancellation flag set for rq job %s", job_id)
        return True
    except Exception as exc:  # pragma: no cover - depends on Redis
        log.warning("could not set cancel flag for %s: %s", job_id, exc)
        return False


def clear_redis(client, job_id: str) -> None:
    try:
        client.delete(f"{_REDIS_PREFIX}{job_id}")
    except Exception:  # pragma: no cover - depends on Redis
        pass
