"""core.tasks — background job queue for the aggregation pipeline (Sprint 06, B2).

Wraps rq (Redis Queue) behind a tiny uniform interface so the API layer does
not care which backend is running:

- ``enqueue_pipeline_job`` returns a job id.
- ``get_job_status`` returns ``{status, records?, error?}``.
- ``cancel_job`` attempts to cancel a queued (not yet started) job.

When ``REDIS_URL`` is set *and* Redis is reachable, jobs run through rq on a
worker process (see ``docker-compose.yml`` ``worker`` service and the ``rq``
CLI). Otherwise the module falls back to an in-process daemon thread so the
API keeps working in dev and in the test suite with zero extra services.

The worker entrypoint is :func:`run_pipeline_job`; keep its signature and
module path stable (rq looks jobs up by that dotted name).

Sprint 07 adds the weekly email digest: :func:`enqueue_digest_job` /
:func:`send_digest_job` run through the same queue, plus a weekly scheduler
(:func:`schedule_weekly_digests`) that enqueues one digest per opted-in user.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
import uuid
from typing import Optional

from sqlalchemy import select

from core import cache, cancel as cancel_mod, email
from core.config import build_config
from pipeline.run import run as pipeline_run

log = logging.getLogger("core.tasks")

# Sprint 09 (B3): transient failures are retried before a job is declared
# failed. ``CIK_JOB_RETRIES`` is the number of *further* attempts after the
# first, ``CIK_JOB_RETRY_DELAY`` the backoff between them (seconds).
MAX_PIPELINE_RETRIES = max(0, int(os.environ.get("CIK_JOB_RETRIES", "2")))
RETRY_BACKOFF_S = max(0.0, float(os.environ.get("CIK_JOB_RETRY_DELAY", "2")))

# Fallback (no Redis): job_id -> {status, records?, error?}
_in_memory_jobs: dict[str, dict] = {}
_in_memory_jobs_lock = threading.Lock()
_fallback_slots = threading.Semaphore(3)  # mirrors the old concurrency cap
# Supervisor syncs are heavy and share the same SQLite DB — never run two at
# once, and don't let them pile up behind pipeline runs.
_supervisor_slots = threading.Semaphore(1)

# Cross-worker idempotency for the weekly digest batch (one claim per UTC day).
_digest_run_day: Optional[str] = None
_digest_run_lock = threading.Lock()


# --- per-source progress (M3: streamed to the run dialog) ---------------------
def _apply_progress(prog: dict, event: dict) -> None:
    """Fold one fetch_sources progress event into a job's progress dict."""
    if event.get("event") == "start":
        prog["total"] = event.get("total", 0)
        prog["completed"] = 0
        prog["sources"] = []
    elif event.get("event") == "funnel":
        # End-of-run accounting: found -> filtered -> deduped -> stored, with
        # the reason for every drop. Surfaced so the UI headline number and
        # the engine's number can never disagree unexplained.
        prog["funnel"] = {k: v for k, v in event.items() if k != "event"}
    elif event.get("event") == "source":
        prog.setdefault("sources", []).append({
            "source": event.get("source"),
            "status": event.get("status"),
            "records": event.get("records", 0),
            "duration": event.get("duration"),
        })
        prog["completed"] = len(prog["sources"])


def _inproc_progress_callback(job_id: str):
    """Thread-safe callback recording per-source progress on the in-memory job
    record (fallback path); read back by :func:`get_job_status`."""
    def cb(event: dict) -> None:
        with _in_memory_jobs_lock:
            rec = _in_memory_jobs.get(job_id)
            if rec is None:
                return
            prog = rec.get("progress") or {"total": 0, "completed": 0,
                                           "sources": []}
            _apply_progress(prog, event)
            rec["progress"] = prog
    return cb


def _rq_progress_callback():
    """Inside an rq worker, return a thread-safe callback that accumulates
    per-source progress into the job's meta. Returns None when not in a job."""
    try:
        from rq import get_current_job
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return None
    lock = threading.Lock()

    def cb(event: dict) -> None:
        with lock:
            prog = (job.meta or {}).get("progress") or {
                "total": 0, "completed": 0, "sources": []}
            _apply_progress(prog, event)
            job.meta["progress"] = prog
            try:
                job.save_meta()
            except Exception:  # pragma: no cover - depends on Redis
                pass
    return cb


def _rq_cancel_token():
    """Redis-backed cancellation token for the current rq job, if any.

    Inside a worker the job runs in a different PROCESS from the API, so an
    in-process Event is invisible. Falls back to a no-op token outside rq.
    """
    try:
        from rq import get_current_job
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return cancel_mod.NullToken()
    client = _redis()
    if client is None:  # pragma: no cover - rq implies Redis
        return cancel_mod.NullToken()
    return cancel_mod.RedisToken(client, job.id)


def run_pipeline_job(country: str | None = None,
                     sources: list[str] | None = None,
                     field: str | None = None,
                     on_progress=None,
                     subfields: list[str] | None = None,
                     cancel=None,
                     include_slow: bool = False,
                     position_types: list[str] | None = None) -> int:
    """Execute the aggregation pipeline and return the number of records.

    The return value (an ``int`` record count) is stored as the rq *result* for
    the job, which the API surfaces via :func:`get_job_status` as ``records``.
    Also invalidates the cached lists (B1) so fresh data is served. This is the
    rq worker entrypoint — importable by dotted path ``core.tasks.run_pipeline_job``.

    ``field`` selects the field profile (fields/<field>.yaml) the crawl scores
    and filters against, so the dashboard's field dropdown changes what a run
    collects. When omitted the built-in default taxonomy is used (unchanged
    behaviour).
    """
    args = argparse.Namespace(
        country=[country] if country else None,
        field=field or None,
        # Selected subfields BOOST matching positions (their keywords join
        # context_terms) rather than gating them — see apply_subfield_focus.
        subfields=list(subfields or []),
        include_slow_sources=bool(include_slow),
        # PhD and postdoc are separate searches, each with its own results.
        types=list(position_types) if position_types else None,
        no_config=True,
    )
    cfg = build_config(args)
    # In the rq worker no callback is passed in — discover the current job and
    # stream progress into its meta so the API can poll per-source status.
    if on_progress is None:
        on_progress = _rq_progress_callback()
    # In an rq worker nobody hands us a token — build the Redis-backed one so
    # the API process (a DIFFERENT process) can still stop this run.
    if cancel is None:
        cancel = _rq_cancel_token()
    funnel: dict = {}
    records = pipeline_run(cfg, only_sources=sources, on_progress=on_progress,
                           funnel=funnel, cancel=cancel)
    # The pipeline writes JSON/CSV/HTML; the dashboard reads the ``opportunities``
    # table, so re-seed it from the JSON just written (idempotent upsert). A
    # seeding failure must not fail the job — the run already succeeded — but it
    # must not be invisible either: when seeding fails the dashboard keeps
    # showing the OLD row count while the engine reports the new one, which is
    # exactly how "18 open positions" and "63 records" drift apart. Record it.
    try:
        from db.init import (count_opportunities, init_db, resolve_db_url,
                             seed_from_json)
        engine = init_db(resolve_db_url())
        with Session(engine) as session:
            seed_from_json(session, cfg.json_path)
            funnel["stored"] = count_opportunities(session)
        # Invalidate BEFORE anything else can read a stale list. Keyed by
        # field, so switching field can never serve the previous field's rows.
        cache.invalidate_opportunities()
    except Exception as exc:
        funnel["storage_error"] = str(exc)
        log.warning("pipeline job %s: DB seeding failed (%s) — outputs written "
                    "to %s, dashboard may be stale", country, exc, cfg.json_path)
    cache.invalidate_supervisors()
    cache.invalidate_matches()
    if on_progress is not None:
        # Final event: the funnel, so the UI can explain every drop.
        try:
            on_progress({"event": "funnel", **funnel})
        except Exception as exc:  # never let reporting break a finished run
            log.debug("funnel callback failed: %s", exc)
    return len(records)


def _redis():
    """Return the shared Redis client from core.cache (reused, not recreated)."""
    return cache._get_redis()


def _fallback_run(job_id: str, country: str | None,
                  sources: list[str] | None, field: str | None = None,
                  attempt: int = 1, subfields: list[str] | None = None,
                  include_slow: bool = False,
                  position_types: list[str] | None = None) -> None:
    is_final: Optional[bool] = None
    token = cancel_mod.get(job_id) or cancel_mod.register(job_id)
    try:
        records = run_pipeline_job(country, sources, field,
                                   on_progress=_inproc_progress_callback(job_id),
                                   subfields=subfields, cancel=token,
                                   include_slow=include_slow,
                                   position_types=position_types)
        with _in_memory_jobs_lock:
            prev = _in_memory_jobs.get(job_id, {})
            # A cancelled run still SUCCEEDED — it just stopped early. Its
            # partial results are already filtered, deduped and stored, so
            # report the count rather than discarding the work.
            _in_memory_jobs[job_id] = {
                "job_id": job_id,
                "status": ("cancelled" if token.is_cancelled() else "completed"),
                "records": records,
                "attempts": attempt,
                "progress": prev.get("progress")}
        is_final = True
    except Exception as exc:
        log.warning("pipeline job %s failed (attempt %s/%s): %s",
                    job_id, attempt, MAX_PIPELINE_RETRIES + 1, exc)
        if attempt <= MAX_PIPELINE_RETRIES:
            # transient failure — schedule a retry after the backoff. This
            # attempt does not free the concurrency slot; the retry chain
            # finishes it when a terminal state is reached.
            time.sleep(RETRY_BACKOFF_S)
            threading.Thread(target=_fallback_run,
                             args=(job_id, country, sources, field,
                                   attempt + 1, subfields, include_slow,
                                   position_types),
                             daemon=True).start()
            is_final = False
        else:
            with _in_memory_jobs_lock:
                if _in_memory_jobs.get(job_id, {}).get("status") != "cancelled":
                    _in_memory_jobs[job_id] = {"job_id": job_id,
                                               "status": "failed",
                                               "error": str(exc),
                                               "attempts": attempt}
            is_final = True
    finally:
        if is_final:
            # Retries reuse the token (a cancel during attempt 1 must still
            # apply to attempt 2), so only drop it on a terminal state.
            cancel_mod.release(job_id)
            _fallback_slots.release()


def _enqueue_fallback(country, sources, field=None,
                      subfields=None, include_slow=False,
                      position_types=None) -> str:
    job_id = uuid.uuid4().hex[:12]
    if not _fallback_slots.acquire(blocking=False):
        raise RuntimeError("Too many concurrent pipeline runs — try again later")
    with _in_memory_jobs_lock:
        _in_memory_jobs[job_id] = {"job_id": job_id, "status": "running",
                                   "country": country, "sources": sources,
                                   "field": field, "subfields": subfields,
                                   "created_at": time.time(), "attempts": 1}
    threading.Thread(target=_fallback_run,
                     args=(job_id, country, sources, field, 1, subfields,
                           include_slow, position_types),
                     daemon=True).start()
    return job_id


def _enqueue_rq(country, sources, field=None, subfields=None,
                include_slow=False, position_types=None) -> str:
    from rq import Queue
    client = _redis()
    q = Queue(connection=client)
    job_id = uuid.uuid4().hex[:12]
    retry = None
    if MAX_PIPELINE_RETRIES:
        try:
            from rq import Retry
            retry = Retry(max=MAX_PIPELINE_RETRIES,
                          interval=[RETRY_BACKOFF_S] * MAX_PIPELINE_RETRIES)
        except Exception:
            retry = None
    # Explicit args=/kwargs= — run_pipeline_job's 4th positional is
    # on_progress, so subfields must travel as a keyword.
    job = q.enqueue(run_pipeline_job,
                    args=(country, sources, field),
                    kwargs={"subfields": list(subfields or []),
                            "include_slow": bool(include_slow),
                            "position_types": list(position_types or []) or None},
                    job_id=job_id,
                    retry=retry,
                    result_ttl=3600, failure_ttl=86400)
    return job.id


def enqueue_pipeline_job(country: str | None = None,
                         sources: list[str] | None = None,
                         field: str | None = None,
                         subfields: list[str] | None = None,
                         include_slow: bool = False,
                         position_types: list[str] | None = None) -> str:
    """Start a pipeline run; returns the job id.

    ``field`` names the field profile to crawl/score under (e.g. ``biology``);
    ``None`` keeps the server default taxonomy. ``subfields`` are ids within
    that profile whose keywords boost matching positions.
    """
    client = _redis()
    if client is not None:
        return _enqueue_rq(country, sources, field, subfields, include_slow,
                           position_types)
    return _enqueue_fallback(country, sources, field, subfields, include_slow,
                             position_types)


# ---------------------------------------------------------------------------
# Supervisor search sync (desktop "run online search" button)
# ---------------------------------------------------------------------------
def run_supervisor_sync_job(countries: list[str],
                            field: str | None = None,
                            quick: bool = True,
                            limit: int | None = None) -> int:
    """Aggregate + upsert supervisor candidates; returns the number upserted.

    rq/thread worker entrypoint for :func:`enqueue_supervisor_job`. Runs the
    same code path as the ``--sync-supervisors`` CLI but in a lighter
    (``quick``) mode so an interactive search from the desktop UI finishes in
    reasonable time. Invalidate the supervisor cache so fresh rows are served.
    """
    from cli.commands import sync_supervisors
    from db.init import resolve_db_url

    upserted, _ = sync_supervisors(countries, field=field,
                                   db_url=resolve_db_url(), quick=quick,
                                   limit=limit)
    return upserted


def _fallback_supervisor_run(job_id: str, countries: list[str],
                             field: str | None, quick: bool,
                             attempt: int = 1,
                             limit: int | None = None) -> None:
    is_final: Optional[bool] = None
    try:
        records = run_supervisor_sync_job(countries, field, quick, limit)
        with _in_memory_jobs_lock:
            if _in_memory_jobs.get(job_id, {}).get("status") != "cancelled":
                _in_memory_jobs[job_id] = {"job_id": job_id,
                                           "status": "completed",
                                           "records": records,
                                           "attempts": attempt}
        is_final = True
    except Exception as exc:
        log.warning("supervisor sync job %s failed (attempt %s/%s): %s",
                    job_id, attempt, MAX_PIPELINE_RETRIES + 1, exc)
        if attempt <= MAX_PIPELINE_RETRIES:
            time.sleep(RETRY_BACKOFF_S)
            threading.Thread(target=_fallback_supervisor_run,
                             args=(job_id, countries, field, quick, attempt + 1),
                             daemon=True).start()
            is_final = False
        else:
            with _in_memory_jobs_lock:
                if _in_memory_jobs.get(job_id, {}).get("status") != "cancelled":
                    _in_memory_jobs[job_id] = {"job_id": job_id,
                                               "status": "failed",
                                               "error": str(exc),
                                               "attempts": attempt}
            is_final = True
    finally:
        if is_final:
            _supervisor_slots.release()


def enqueue_supervisor_job(countries: list[str],
                           field: str | None = None,
                           quick: bool = True,
                           limit: int | None = None) -> str:
    """Start a supervisor search sync; returns the job id (poll with
    :func:`get_job_status`, same as pipeline jobs)."""
    countries = [c.strip() for c in countries if c and c.strip()]
    if not countries:
        raise ValueError("at least one country is required")
    client = _redis()
    if client is not None:
        from rq import Queue
        q = Queue(connection=client)
        job_id = uuid.uuid4().hex[:12]
        job = q.enqueue(run_supervisor_sync_job,
                        args=(countries, field, quick),
                        kwargs={"limit": limit},
                        job_id=job_id,
                        result_ttl=3600, failure_ttl=86400)
        return job.id
    job_id = uuid.uuid4().hex[:12]
    if not _supervisor_slots.acquire(blocking=False):
        raise RuntimeError("A supervisor search is already running — wait for "
                           "it to finish before starting another.")
    with _in_memory_jobs_lock:
        _in_memory_jobs[job_id] = {"job_id": job_id, "status": "running",
                                   "country": ", ".join(countries),
                                   "field": field,
                                   "created_at": time.time(), "attempts": 1}
    threading.Thread(target=_fallback_supervisor_run,
                     args=(job_id, countries, field, quick, 1, limit),
                     daemon=True).start()
    return job_id


def get_job_status(job_id: str) -> dict | None:
    """Return ``{status, records?, error?}`` for a job id, or None."""
    client = _redis()
    if client is not None:
        from rq.job import Job
        try:
            job = Job.fetch(job_id, connection=client)
        except Exception:
            return None
        state = job.get_status()
        result = job.result
        exc = job.exc_info
        progress = (job.meta or {}).get("progress")
        if state in ("finished", "completed"):
            return {"job_id": job_id, "status": "completed",
                    "records": result if isinstance(result, int) else None,
                    "progress": progress}
        if state == "failed":
            return {"job_id": job_id, "status": "failed",
                    "error": (exc or "job failed")[:2000],
                    "progress": progress}
        if state in ("started", "deferred"):
            return {"job_id": job_id, "status": "running",
                    "progress": progress}
        if state == "queued":
            return {"job_id": job_id, "status": "queued"}
        if state == "cancelled":
            return {"job_id": job_id, "status": "cancelled"}
        return {"job_id": job_id, "status": state}
    with _in_memory_jobs_lock:
        return dict(_in_memory_jobs[job_id]) if job_id in _in_memory_jobs else None


def jobs_snapshot() -> dict:
    """Counts of all known jobs across the active backend (for the admin
    dashboard, C4). Uses rq registries when Redis is up, the in-memory dict
    otherwise."""
    client = _redis()
    if client is not None:
        from rq import Queue
        try:
            q = Queue(connection=client)
            queued = q.count
            started = len(q.started_job_registry)
            finished = len(q.finished_job_registry)
            failed = len(q.failed_job_registry)
            return {
                "backend": "rq",
                "pending": queued,
                "running": started,
                "completed": finished,
                "failed": failed,
                "total": queued + started + finished + failed,
            }
        except Exception as exc:  # pragma: no cover - depends on Redis
            log.warning("rq snapshot failed: %s", exc)
            return {"backend": "rq", "error": str(exc)}
    with _in_memory_jobs_lock:
        values = list(_in_memory_jobs.values())
    counts = {"pending": 0, "running": 0, "completed": 0,
              "failed": 0, "cancelled": 0}
    for info in values:
        status = info.get("status", "")
        if status in counts:
            counts[status] += 1
        else:
            counts["pending"] += 1
    counts["total"] = sum(counts.values())
    counts["backend"] = "in-process"
    return counts


# ---------------------------------------------------------------------------
# Sprint 09 — B3: dead-letter review, retry, worker heartbeat
# ---------------------------------------------------------------------------
def dead_letters(limit: int = 50) -> list[dict]:
    """List failed (dead-letter) jobs for review, newest first.

    Uses the rq failed registry when Redis is up, else the in-memory job
    dict. Returns one entry per job: ``job_id``, ``status``, ``error``,
    ``created_at``, ``attempts``.
    """
    client = _redis()
    if client is not None:
        from rq import Queue
        from rq.job import Job
        try:
            q = Queue(connection=client)
            ids = q.failed_job_registry.get_job_ids()[:limit]
            out = []
            for jid in ids:
                try:
                    job = Job.fetch(jid, connection=client)
                except Exception:
                    continue
                out.append({
                    "job_id": jid, "status": "failed",
                    "error": ((job.exc_info or job.meta.get("error") or
                               "job failed")[:2000]),
                    "created_at": (job.created_at.isoformat()
                                   if job.created_at else None),
                    "attempts": (job.meta.get("retries", 0) + 1
                                 if job.meta.get("retries") else 1),
                })
            return out
        except Exception as exc:  # pragma: no cover - depends on Redis
            log.warning("rq dead-letter list failed: %s", exc)
            return [{"error": str(exc)}]
    with _in_memory_jobs_lock:
        values = [dict(v) for v in _in_memory_jobs.values()]
    failed = [v for v in values if v.get("status") == "failed"]
    failed.sort(key=lambda v: v.get("created_at") or 0, reverse=True)
    return [{
        "job_id": v["job_id"], "status": "failed",
        "error": (v.get("error") or "job failed")[:2000],
        "created_at": v.get("created_at"),
        "attempts": v.get("attempts", 1),
    } for v in failed[:limit]]


def retry_job(job_id: str) -> Optional[str]:
    """Requeue a dead-letter job; returns the (possibly new) job id, or None
    when the job is not retryable/known."""
    client = _redis()
    if client is not None:
        from rq import Queue
        from rq.job import Job
        try:
            q = Queue(connection=client)
            job = Job.fetch(job_id, connection=client)
            if job.get_status() != "failed":
                return None
            q.failed_job_registry.requeue(job_id)
            return job_id
        except Exception as exc:  # pragma: no cover - depends on Redis
            log.warning("rq requeue failed: %s", exc)
            return None
    with _in_memory_jobs_lock:
        info = _in_memory_jobs.get(job_id)
        if info is None or info.get("status") != "failed":
            return None
        country = info.get("country")
        sources = info.get("sources")
        field = info.get("field")
        del _in_memory_jobs[job_id]
    return _enqueue_fallback(country, sources, field)


def worker_heartbeat() -> dict:
    """Per-worker heartbeat info (rq) for the admin dashboard."""
    client = _redis()
    if client is not None:
        try:
            from rq import Worker
            beats = Worker.all_heartbeats(connection=client)
            return {"backend": "rq", "workers": beats,
                    "now_ts": time.time()}
        except Exception as exc:  # pragma: no cover - depends on Redis
            log.warning("worker heartbeat lookup failed: %s", exc)
            return {"backend": "rq", "error": str(exc)}
    return {"backend": "in-process", "workers": {}}


def cancel_job(job_id: str) -> bool:
    """Stop a job — queued OR already running. True if the request landed.

    A RUNNING crawl is cancelled cooperatively (see :mod:`core.cancel`): the
    source in flight finishes its current request, sources not yet started are
    skipped, and everything collected so far is still filtered, deduped and
    stored. The user keeps the partial results and the app stays usable —
    nothing is killed, no process is signalled, no restart is needed.
    """
    client = _redis()
    if client is not None:
        from rq.job import Job
        try:
            job = Job.fetch(job_id, connection=client)
        except Exception:
            return False
        status = job.get_status()
        if status == "queued":
            job.cancel()          # never started: drop it outright
            return True
        if status == "started":
            # Running in another process — raise the flag its token polls.
            return cancel_mod.request_cancel_redis(client, job_id)
        return False
    with _in_memory_jobs_lock:
        info = _in_memory_jobs.get(job_id)
        if info is None or info["status"] != "running":
            return False
    # Signal the worker thread. The status is NOT forced here: the run itself
    # records "cancelled" once it has finished storing its partial results, so
    # a poll can never report a terminal state before the data is saved.
    if cancel_mod.request_cancel(job_id):
        return True
    with _in_memory_jobs_lock:
        info = _in_memory_jobs.get(job_id)
        if info is not None and info["status"] == "running":
            info["status"] = "cancelled"   # no live token (e.g. between retries)
            return True
    return False


# ---------------------------------------------------------------------------
# Sprint 07 — weekly email digest
# ---------------------------------------------------------------------------
DIGEST_WEEKDAY = 0          # Monday
DIGEST_HOUR_UTC = 8         # 08:00 UTC


def send_digest_job(profile_id: int, session_factory=None) -> int:
    """Build + send one user's weekly digest. Returns emails sent (0/1).

    Never raises: any failure is logged and recorded as an email_events row so
    the weekly sweep cannot crash the worker. This is the rq entrypoint —
    keep the dotted path ``core.tasks.send_digest_job`` stable.

    ``session_factory`` may be injected for tests (callable returning a
    SQLAlchemy Session); defaults to a fresh session over the default engine.
    """
    if session_factory is None:
        from db.init import init_db, resolve_db_url
        from sqlalchemy.orm import Session
        engine = init_db(resolve_db_url())
        session_factory = lambda: Session(engine)  # noqa: E731
    try:
        with session_factory() as session:
            return _send_digest_for_profile(session, profile_id)
    except Exception:
        log.exception("send_digest_job(%s) failed", profile_id)
        return 0


def _send_digest_for_profile(session, profile_id: int) -> int:
    """The digest pipeline for one profile (shared by rq + fallback paths)."""
    from sqlalchemy import select
    from db.repositories import EmailEventRepo, ProfileRepo
    from db.models import DigestPreference, UserProfileRow

    row = session.get(UserProfileRow, profile_id)
    if row is None:
        log.warning("digest: no profile row %s — skipping", profile_id)
        return 0
    pref = session.get(DigestPreference, profile_id)
    if pref is None or pref.frequency in (None, "", "never"):
        log.info("digest: profile %s has no weekly preference — skipping",
                 profile_id)
        return 0
    email_to = pref.email
    if not email_to and row.user_id is not None:
        from db.models import User
        user = session.get(User, row.user_id)
        email_to = user.email if user else None
    if not email_to:
        log.warning("digest: profile %s has no target email — skipping",
                    profile_id)
        return 0

    # Recompute the scored matches deterministically (same engine the API uses).
    from core.profile_schema import UserProfile
    from core.config import build_config
    profile = UserProfile(**row.to_profile())
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
        "title": opp.title,
        "institution": opp.institution,
        "country": opp.country,
        "url": opp.url,
        "deadline": opp.deadline,
        "funding_status": opp.funding_status,
        "short_description": opp.short_description,
        "match_score": result.overall_score,
        "match_explanation": result.explanation,
    } for opp, result in zip(opps, results)]

    from core.digest import build_digest
    digest = build_digest(
        profile,
        positions=scored,
        supervisors=[],  # supervisor list requires a fetch — Sprint 09 expands
        include_supervisors=bool(pref.include_supervisors),
    )

    result = email.send_email(email_to, digest["subject"], digest["html"],
                              text=digest["text"])
    repo = EmailEventRepo(session)
    repo.record(email_to=email_to, event_type=result["status"],
                subject=digest["subject"], provider_id=result.get("id"))
    session.commit()
    log.info("digest %s for profile %s -> %s (id=%s)",
             result["status"], profile_id, email_to, result.get("id"))
    return 1 if result["status"] == "sent" else 0


def enqueue_digest_job(profile_id: int) -> str:
    """Queue a weekly digest for one profile; returns the job id."""
    client = _redis()
    if client is not None:
        from rq import Queue
        q = Queue(connection=client)
        job = q.enqueue(send_digest_job, profile_id,
                        job_id=f"digest-{profile_id}-{uuid.uuid4().hex[:6]}",
                        result_ttl=3600, failure_ttl=86400)
        return job.id
    # In-process fallback: run synchronously in a daemon thread.
    job_id = uuid.uuid4().hex[:12]
    with _in_memory_jobs_lock:
        _in_memory_jobs[job_id] = {"job_id": job_id, "status": "running"}
    threading.Thread(target=_run_digest_fallback,
                     args=(job_id, profile_id), daemon=True).start()
    return job_id


def _run_digest_fallback(job_id: str, profile_id: int) -> None:
    try:
        count = send_digest_job(profile_id)
        with _in_memory_jobs_lock:
            if _in_memory_jobs.get(job_id, {}).get("status") != "cancelled":
                _in_memory_jobs[job_id] = {"job_id": job_id,
                                           "status": "completed",
                                           "records": count}
    except Exception as exc:
        log.exception("digest job %s failed", job_id)
        with _in_memory_jobs_lock:
            if _in_memory_jobs.get(job_id, {}).get("status") != "cancelled":
                _in_memory_jobs[job_id] = {"job_id": job_id,
                                           "status": "failed",
                                           "error": str(exc)}


# ---------------------------------------------------------------------------
# Transactional emails (verification / reset) — queued, never inline
# ---------------------------------------------------------------------------
def send_email_job(to: str, subject: str, html: str,
                   text: Optional[str] = None) -> dict:
    """rq entrypoint for transactional emails; never raises.

    Returns the same ``{status, id}`` shape as :func:`core.email.send_email` so
    callers can record delivery. This is the dotted rq entrypoint for
    :func:`enqueue_transactional_email`.
    """
    try:
        return email.send_email(to, subject, html, text=text)
    except Exception:  # pragma: no cover - send_email already swallows errors
        log.exception("send_email_job failed to=%s", to)
        return {"status": "failed", "id": None}


def _run_transactional_fallback(job_id: str, to: str, subject: str,
                                html: str, text: Optional[str] = None) -> None:
    send_email_job(to, subject, html, text=text)


def enqueue_transactional_email(to: str, subject: str, html: str,
                                text: Optional[str] = None) -> str:
    """Dispatch one transactional email off the request path.

    Uses rq when Redis is up; otherwise runs the send in a daemon thread so an
    HTTP request never blocks on a network send (in dev — no ``RESEND_API_KEY``
    — the fallback is a cheap no-op log). Returns the job id.
    """
    client = _redis()
    if client is not None:
        from rq import Queue
        q = Queue(connection=client)
        job = q.enqueue(send_email_job, to, subject, html, text,
                        job_id=f"email-{uuid.uuid4().hex[:12]}",
                        result_ttl=3600, failure_ttl=86400)
        return job.id
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_run_transactional_fallback,
                     args=(job_id, to, subject, html, text), daemon=True).start()
    return job_id


def _claim_digest_run() -> bool:
    """Atomically claim today's digest batch (cross-worker idempotency).

    Returns True the first time per UTC day, False afterwards. Uses a Redis
    SET NX so multiple workers / duplicate rq-scheduler crons cannot double-run
    the batch; falls back to an in-process claim when Redis is absent (each
    process then fires at most once per day, which is the dev guarantee).
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = _redis()
    if client is not None:
        try:
            return bool(client.set(_LAST_DIGEST_RUN_KEY, today,
                                   ex=48 * 3600, nx=True))
        except Exception:  # pragma: no cover - depends on Redis
            log.warning("digest claim via Redis failed — using in-process guard")
    global _digest_run_day
    with _digest_run_lock:
        if _digest_run_day == today:
            return False
        _digest_run_day = today
        return True


def schedule_weekly_digests(session=None) -> int:
    """Enqueue one digest job per profile with a weekly digest preference.

    Called by the rq-scheduler cron (``0 8 * * 1``) in production or by the
    in-process daily check (see :func:`start_digest_scheduler`) in dev. Returns
    the number of jobs enqueued.

    Idempotent per UTC day: :func:`_claim_digest_run` is an atomic SET NX, so
    even if every uvicorn worker registers the cron (or the fallback thread
    fires alongside a worker), the batch runs at most once.
    """
    if not _claim_digest_run():
        log.info("weekly digest batch already claimed today — skipping")
        return 0
    try:
        from sqlalchemy import select
        if session is None:
            from db.init import init_db, resolve_db_url
            from sqlalchemy.orm import Session
            engine = init_db(resolve_db_url())
            with Session(engine) as session:
                return _schedule_weekly_digests(session)
        return _schedule_weekly_digests(session)
    except Exception:
        # A catastrophic batch failure releases the claim so the next hourly
        # wakeup / cron retries instead of waiting until tomorrow.
        _release_digest_run()
        raise


def _release_digest_run() -> None:
    """Undo a :func:`_claim_digest_run` so a failed batch can be retried."""
    client = _redis()
    if client is not None:
        try:
            client.delete(_LAST_DIGEST_RUN_KEY)
        except Exception:  # pragma: no cover - depends on Redis
            pass
    global _digest_run_day
    with _digest_run_lock:
        _digest_run_day = None


def _schedule_weekly_digests(session) -> int:
    from db.models import DigestPreference
    rows = session.scalars(
        select(DigestPreference.profile_id)
        .where(DigestPreference.frequency == "weekly")).all()
    enqueued = 0
    for profile_id in rows:
        try:
            enqueue_digest_job(profile_id)
            enqueued += 1
        except Exception as exc:  # one bad profile never blocks the rest
            log.warning("digest enqueue for profile %s failed: %s",
                        profile_id, exc)
    log.info("scheduled %d weekly digest job(s)", enqueued)
    return enqueued


def rollup_api_key_usage(session=None) -> int:
    """Persist the live API-key request counters into ``api_key_usage`` rows.

    Nightly job (rq-scheduler cron ``0 3 * * *``) or on-demand dev call: reads
    the Redis/in-memory meters from :data:`core.ratelimit.api_key_meter` and
    accumulates per key/day counts so ``/usage`` and the admin dashboard can
    chart real request volume even after the Redis buckets expire (48h TTL).
    ``session`` may be injected for tests. Returns the number of keys written.
    """
    from core.ratelimit import api_key_meter
    if session is None:
        from db.init import init_db, resolve_db_url
        from sqlalchemy.orm import Session
        engine = init_db(resolve_db_url())
        with Session(engine) as session:
            return _rollup_api_key_usage(session, api_key_meter)
    return _rollup_api_key_usage(session, api_key_meter)


def _rollup_api_key_usage(session, meter) -> int:
    from db.repositories import ApiKeyUsageRepo
    repo = ApiKeyUsageRepo(session)
    keys = meter.active_keys()
    for key_id, day in keys:
        requests, rate_limited = meter.snapshot(key_id, day=day)
        repo.upsert_usage(key_id, day, requests, rate_limited)
    session.commit()
    return len(keys)


_LAST_DIGEST_RUN_KEY = "digest:last_scheduled_iso"


def start_digest_scheduler() -> Optional[threading.Thread]:
    """Start the weekly-digest scheduler.

    With Redis + rq-scheduler available this registers a cron and returns
    None; otherwise a daemon thread checks hourly whether it is digest-time and
    enqueues the weekly batch at most once per day. Returns the daemon thread
    in the fallback path (dev), else None.
    """
    client = _redis()
    if client is not None:
        try:
            from rq_scheduler import Scheduler  # type: ignore
            scheduler = Scheduler(connection=client)
            scheduler.cron(
                "0 8 * * 1",
                func=schedule_weekly_digests,
                repeat=None,
                queue_name="default",
            )
            log.info("weekly digest cron registered via rq-scheduler")
            return None
        except Exception as exc:
            log.warning("rq-scheduler unavailable (%s) — using in-process "
                        "daily check", exc)

    def _daily_check() -> None:
        from datetime import datetime, timezone
        while True:
            now = datetime.now(timezone.utc)
            if (now.weekday() == DIGEST_WEEKDAY and
                    now.hour == DIGEST_HOUR_UTC):
                try:
                    # The per-day idempotency claim lives inside
                    # schedule_weekly_digests, so this hourly window can only
                    # produce ONE batch even if several check threads awake.
                    schedule_weekly_digests()
                except Exception:
                    log.exception("weekly digest batch failed")
            time.sleep(3600)  # check once an hour

    t = threading.Thread(target=_daily_check, daemon=True,
                         name="weekly-digest-check")
    t.start()
    return t
