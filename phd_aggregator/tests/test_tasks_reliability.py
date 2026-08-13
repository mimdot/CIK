"""tests.test_tasks_reliability — Sprint 09, Track B3 (job retries,
dead-letter review + requeue, worker heartbeat). All exercised through the
in-memory fallback backend with a mocked ``run_pipeline_job`` so the suite
stays offline and deterministic.
"""

from __future__ import annotations

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

    def flaky(country=None, sources=None, field=None, on_progress=None):
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
    def always_fails(country=None, sources=None, field=None, on_progress=None):
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

    def run(country=None, sources=None, field=None, on_progress=None):
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
                        on_progress=None: 7)
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