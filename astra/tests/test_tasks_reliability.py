"""tests.test_tasks_reliability — Sprint 09, Track B3 (job retries,
dead-letter review + requeue, worker heartbeat). All exercised through the
in-memory fallback backend with a mocked ``run_pipeline_job`` so the suite
stays offline and deterministic.
"""

from __future__ import annotations

import threading
import time

import pytest

from core import tasks


@pytest.fixture()
def no_redis(monkeypatch):
    monkeypatch.setattr(tasks, "_redis", lambda: None)
    monkeypatch.setattr(tasks, "RETRY_BACKOFF_S", 0.0)
    tasks._in_memory_jobs.clear()


def _wait_for(job_id, statuses, deadline=6.0):
    deadline = time.time() + deadline
    while time.time() < deadline:
        info = tasks.get_job_status(job_id)
        if info and info["status"] in statuses:
            return info
        time.sleep(0.02)
    pytest.fail(f"job {job_id} never reached {statuses}: {info}")


def test_transient_failure_is_retried_then_succeeds(monkeypatch, no_redis):
    calls = {"n": 0}

    def flaky(country=None, sources=None, field=None, on_progress=None, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient network error")
        return 5

    monkeypatch.setattr(tasks, "run_pipeline_job", flaky)
    monkeypatch.setattr(tasks, "MAX_PIPELINE_RETRIES", 2)
    job_id = tasks.enqueue_pipeline_job(country="Germany")
    info = _wait_for(job_id, {"completed", "failed"})
    assert info["status"] == "completed"
    assert info["records"] == 5
    assert info["attempts"] == 2
    assert calls["n"] == 2


def test_persistent_failure_lands_in_dead_letters(monkeypatch, no_redis):
    def always_fails(country=None, sources=None, field=None, on_progress=None, **_kw):
        raise ValueError("boom")

    monkeypatch.setattr(tasks, "run_pipeline_job", always_fails)
    monkeypatch.setattr(tasks, "MAX_PIPELINE_RETRIES", 1)
    job_id = tasks.enqueue_pipeline_job(country="DE", sources=["eso"])
    info = _wait_for(job_id, {"failed"})
    assert info["status"] == "failed"
    assert "boom" in info["error"]

    letters = tasks.dead_letters()
    assert any(l["job_id"] == job_id for l in letters)


def test_retry_job_requeues_failed_fallback(monkeypatch, no_redis):
    fail_first = {"n": 0}

    def run(country=None, sources=None, field=None, on_progress=None, **_kw):
        fail_first["n"] += 1
        if fail_first["n"] <= 3:
            raise OSError("transient")
        return 7

    monkeypatch.setattr(tasks, "run_pipeline_job", run)
    monkeypatch.setattr(tasks, "MAX_PIPELINE_RETRIES", 0)  # no auto retries
    job_id = tasks.enqueue_pipeline_job()
    info = _wait_for(job_id, {"failed"})
    assert info["status"] == "failed"

    # now enable success and manually requeue the dead letter
    monkeypatch.setattr(tasks, "run_pipeline_job",
                        lambda country=None, sources=None, field=None,
                        on_progress=None, **_kw: 7)
    new_id = tasks.retry_job(job_id)
    assert new_id and new_id != job_id
    info = _wait_for(new_id, {"completed", "failed"})
    assert info["status"] == "completed"
    assert info["records"] == 7


def test_retry_job_missing_returns_none(no_redis):
    assert tasks.retry_job("nope") is None


def test_worker_heartbeat_in_process(no_redis):
    beat = tasks.worker_heartbeat()
    assert beat["backend"] == "in-process"
    assert beat["workers"] == {}

# --- the stranded supervisor slot --------------------------------------------

def test_a_dead_supervisor_holder_does_not_strand_the_feature():
    """A slot whose job is gone must be reclaimed, not held for ever.

    Observed live: the backend idle at 0% CPU with no outbound connections,
    the job id already absent from the registry, and every new supervisor
    search refused with "A supervisor search is already running". Only
    restarting the app cleared it, so from the user's side the feature simply
    stopped returning results.
    """
    from core import tasks
    tasks._supervisor_slots = threading.Semaphore(1)
    tasks._supervisor_active = {"job_id": None, "started": 0.0}

    assert tasks._claim_supervisor_slot("job-one")
    # A second claim while job-one is genuinely running must be refused.
    with tasks._in_memory_jobs_lock:
        tasks._in_memory_jobs["job-one"] = {"job_id": "job-one",
                                            "status": "running"}
    tasks._supervisor_active["started"] = time.time() - 600
    assert not tasks._claim_supervisor_slot("job-two")

    # Now job-one disappears the way it did in the field — evicted, thread
    # gone, `finally` never reached. The next search must still be allowed.
    with tasks._in_memory_jobs_lock:
        del tasks._in_memory_jobs["job-one"]
    tasks._supervisor_active["started"] = time.time() - 600
    assert tasks._claim_supervisor_slot("job-three"), (
        "slot stayed held by a job that no longer exists")


def test_a_finished_supervisor_holder_releases_the_slot():
    """A completed holder frees the slot even if its release never ran."""
    from core import tasks
    tasks._supervisor_slots = threading.Semaphore(1)
    tasks._supervisor_active = {"job_id": None, "started": 0.0}

    assert tasks._claim_supervisor_slot("done-job")
    with tasks._in_memory_jobs_lock:
        tasks._in_memory_jobs["done-job"] = {"job_id": "done-job",
                                             "status": "completed"}
    tasks._supervisor_active["started"] = time.time() - 600
    assert tasks._claim_supervisor_slot("next-job")


def test_releasing_a_slot_you_no_longer_own_is_a_no_op():
    """A late release from a reclaimed job must not free someone else's slot."""
    from core import tasks
    tasks._supervisor_slots = threading.Semaphore(1)
    tasks._supervisor_active = {"job_id": None, "started": 0.0}

    tasks._claim_supervisor_slot("old-job")
    tasks._supervisor_active.update({"job_id": "new-job",
                                     "started": time.time()})
    tasks._release_supervisor_slot("old-job")
    assert tasks._supervisor_active["job_id"] == "new-job"
