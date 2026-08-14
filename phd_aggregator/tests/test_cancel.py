"""Cancel a running search cleanly, keeping partial results (Phase 2A).

The requirement: a visible Cancel that stops an in-progress search, cancels
pending work, KEEPS what was already found, and leaves the app in a usable
idle state — no process killed, no crash, no restart.

Before this, ``cancel_job`` could only cancel a job that had not started; a
running crawl ignored it, ran to completion, and had its results discarded.
"""

from __future__ import annotations

import argparse
import threading
import time

import pytest

import pipeline.run as run_mod
from core import cancel as cancel_mod
from core.config import build_config


class _FakeHttp:
    """No-op stand-in so nothing touches the network or the proxy."""

    def __init__(self, cfg, detect=True):
        pass

    def get(self, *a, **kw):
        # The freshness stage probes dateless posts for a page date; None is
        # the "could not read one" answer it already handles.
        return None

    def get_soup(self, *a, **kw):
        return None

    def close(self):
        pass


@pytest.fixture
def slow_sources(monkeypatch):
    """Six sources that each take a beat, run one at a time."""
    calls: list[str] = []
    lock = threading.Lock()

    def make(name):
        def fn(cfg, http):
            with lock:
                calls.append(name)
            time.sleep(0.05)
            return [{"title": f"PhD in radio astronomy ({name})",
                     "url": f"https://example.test/{name}",
                     "source": name,
                     "short_description": "radio astronomy interstellar medium"}]
        return fn

    names = [f"s{i}" for i in range(6)]
    monkeypatch.setattr(run_mod, "SOURCES", {n: make(n) for n in names})
    monkeypatch.setattr(run_mod, "Http", _FakeHttp)
    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 1)
    cfg = build_config(argparse.Namespace(field="astronomy", no_config=True))
    cfg.sources_enabled = {n: True for n in names}
    return cfg, names, calls


# --- the token ---------------------------------------------------------------

def test_null_token_never_cancels():
    assert cancel_mod.NullToken().is_cancelled() is False


def test_event_token_flips_once_cancelled():
    token = cancel_mod.EventToken()
    assert token.is_cancelled() is False
    token.cancel()
    assert token.is_cancelled() is True


def test_registry_round_trip():
    token = cancel_mod.register("j1")
    try:
        assert cancel_mod.get("j1") is token
        assert cancel_mod.request_cancel("j1") is True
        assert token.is_cancelled() is True
    finally:
        cancel_mod.release("j1")
    assert cancel_mod.get("j1") is None
    assert cancel_mod.request_cancel("j1") is False   # gone, not a crash


def test_redis_token_caches_a_positive_and_survives_errors():
    class _Boom:
        def exists(self, key):
            raise RuntimeError("redis down")

    # A Redis hiccup must not abort an otherwise healthy run.
    assert cancel_mod.RedisToken(_Boom(), "j").is_cancelled() is False

    class _Once:
        def __init__(self):
            self.calls = 0

        def exists(self, key):
            self.calls += 1
            return True

    client = _Once()
    token = cancel_mod.RedisToken(client, "j")
    assert token.is_cancelled() is True
    assert token.is_cancelled() is True
    assert client.calls == 1, "a cancelled job must not re-poll Redis"


# --- the crawl stops, and keeps what it found --------------------------------

def test_cancel_stops_remaining_sources(slow_sources):
    cfg, names, calls = slow_sources
    token = cancel_mod.EventToken()
    threading.Timer(0.12, token.cancel).start()

    raw = run_mod.fetch_sources(cfg, cancel=token)

    assert len(calls) < len(names), "should not have run every source"
    assert len(raw) == len(calls), "every source that ran kept its records"
    assert raw, "partial results must be KEPT, not discarded"


def test_cancel_before_the_first_source_yields_nothing_but_no_error(
        slow_sources):
    cfg, names, calls = slow_sources
    token = cancel_mod.EventToken()
    token.cancel()

    raw = run_mod.fetch_sources(cfg, cancel=token)

    assert raw == [] and calls == []


def test_uncancelled_run_is_unaffected(slow_sources):
    cfg, names, calls = slow_sources
    raw = run_mod.fetch_sources(cfg, cancel=cancel_mod.EventToken())
    assert len(calls) == len(names) and len(raw) == len(names)


def test_no_token_at_all_still_works(slow_sources):
    """cancel is optional — every existing caller keeps working."""
    cfg, names, calls = slow_sources
    assert len(run_mod.fetch_sources(cfg)) == len(names)


def test_skipped_sources_are_reported_as_skipped(slow_sources):
    """The UI must be able to show 'skipped', not a fake error or silence."""
    cfg, names, calls = slow_sources
    events: list[dict] = []
    lock = threading.Lock()

    def record(e):
        with lock:
            events.append(e)

    token = cancel_mod.EventToken()
    threading.Timer(0.12, token.cancel).start()
    run_mod.fetch_sources(cfg, on_progress=record, cancel=token)

    statuses = {e["source"]: e["status"] for e in events
                if e.get("event") == "source"}
    assert "skipped" in statuses.values()
    assert "done" in statuses.values()
    # Every source still reports exactly once, so progress counts stay honest.
    assert len(statuses) == len(names)


# --- partial results survive the whole pipeline ------------------------------

def test_cancelled_run_still_filters_dedupes_and_writes(slow_sources, tmp_path):
    cfg, names, calls = slow_sources
    cfg.output_path = str(tmp_path / "positions")
    cfg.write_html = False
    cfg.state_file = str(tmp_path / ".seen.json")

    token = cancel_mod.EventToken()
    threading.Timer(0.12, token.cancel).start()
    funnel: dict = {}
    kept = run_mod.run(cfg, funnel=funnel, cancel=token)

    assert kept, "partial results must reach the user"
    assert funnel["cancelled"] is True, "the UI must be able to say it was cut short"
    assert funnel["found"] == len(calls)
    # Written out like any other run — the data is genuinely saved, not held
    # in memory and dropped.
    import json
    with open(cfg.json_path, encoding="utf-8") as fh:
        assert len(json.load(fh)) == len(kept)


def test_funnel_marks_a_normal_run_as_not_cancelled(slow_sources, tmp_path):
    cfg, names, calls = slow_sources
    cfg.output_path = str(tmp_path / "positions")
    cfg.write_html = False
    cfg.state_file = str(tmp_path / ".seen.json")
    funnel: dict = {}
    run_mod.run(cfg, funnel=funnel, cancel=cancel_mod.EventToken())
    assert funnel["cancelled"] is False


# --- the job layer -----------------------------------------------------------

def test_cancel_job_reaches_a_live_in_process_run():
    from core import tasks
    token = cancel_mod.register("job-live")
    tasks._in_memory_jobs["job-live"] = {"job_id": "job-live",
                                         "status": "running"}
    try:
        assert tasks.cancel_job("job-live") is True
        assert token.is_cancelled() is True
        # Not yet terminal: the run still has partial results to store.
        assert tasks.get_job_status("job-live")["status"] == "running"
    finally:
        cancel_mod.release("job-live")
        tasks._in_memory_jobs.pop("job-live", None)


def test_cancel_job_is_false_for_a_finished_job():
    from core import tasks
    tasks._in_memory_jobs["job-done"] = {"job_id": "job-done",
                                         "status": "completed", "records": 3}
    try:
        assert tasks.cancel_job("job-done") is False
    finally:
        tasks._in_memory_jobs.pop("job-done", None)


def test_cancel_job_is_false_for_an_unknown_job():
    from core import tasks
    assert tasks.cancel_job("no-such-job") is False
