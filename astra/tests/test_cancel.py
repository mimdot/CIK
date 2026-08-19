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


# --- results stream in as they arrive (Phase 6A) -----------------------------

def test_each_source_streams_the_positions_it_found(slow_sources):
    """The search must not look frozen: every source reports its keepers the
    moment it finishes, so the list fills up during the run."""
    cfg, names, calls = slow_sources
    events: list[dict] = []
    lock = threading.Lock()

    def record(e):
        with lock:
            events.append(e)

    run_mod.fetch_sources(cfg, on_progress=record)

    source_events = [e for e in events if e.get("event") == "source"]
    assert len(source_events) == len(names)
    assert all("found" in e for e in source_events)
    assert all(e["found"] for e in source_events), "each source found a keeper"
    first = source_events[0]["found"][0]
    assert first["title"] and first["url"] and first["source"]


def test_streamed_results_are_already_field_filtered(slow_sources,
                                                     monkeypatch):
    """Streaming raw records would show positions that later vanish. The
    preview runs the SAME per-record filter the final pass does."""
    cfg, names, _ = slow_sources

    def mixed(cfg_, http):
        return [
            {"title": "PhD in Radio Astronomy", "url": "https://x/keep",
             "source": "mixed",
             "short_description": "radio astronomy interstellar medium"},
            {"title": "PhD in Medieval Poetry", "url": "https://x/drop",
             "source": "mixed", "short_description": "textual criticism"},
        ]

    monkeypatch.setattr(run_mod, "SOURCES", {"mixed": mixed})
    cfg.sources_enabled = {"mixed": True}
    events: list[dict] = []
    run_mod.fetch_sources(cfg, on_progress=events.append)

    found = [e for e in events if e.get("event") == "source"][0]["found"]
    assert [r["title"] for r in found] == ["PhD in Radio Astronomy"]


def test_the_preview_does_not_disturb_the_real_records(slow_sources):
    """filter_records mutates in place; the preview must work on copies or the
    authoritative pass would see pre-chewed records."""
    cfg, names, _ = slow_sources
    raw = run_mod.fetch_sources(cfg, on_progress=lambda e: None)
    assert raw, "sanity"
    assert all("relevance_score" not in r for r in raw), \
        "the preview leaked its mutations into the real record set"


def test_no_progress_callback_means_no_preview_work(slow_sources):
    """Nobody is watching — do not pay for filtering twice."""
    cfg, names, _ = slow_sources
    assert len(run_mod.fetch_sources(cfg)) == len(names)


def test_the_job_layer_accumulates_and_dedupes_streamed_results():
    from core.tasks import _apply_progress
    prog: dict = {}
    _apply_progress(prog, {"event": "start", "total": 2})
    _apply_progress(prog, {"event": "source", "source": "a", "status": "done",
                           "records": 2, "found": [
                               {"title": "One", "url": "https://x/1"},
                               {"title": "Two", "url": "https://x/2"}]})
    _apply_progress(prog, {"event": "source", "source": "b", "status": "done",
                           "records": 1, "found": [
                               # same advert from another board
                               {"title": "One", "url": "https://x/1"},
                               {"title": "Three", "url": "https://x/3"}]})
    assert prog["found_count"] == 3, "the cross-source duplicate merged"
    assert [r["title"] for r in prog["found"]] == ["One", "Two", "Three"]


def test_a_cancelled_run_keeps_what_it_streamed(slow_sources):
    cfg, names, calls = slow_sources
    token = cancel_mod.EventToken()
    threading.Timer(0.12, token.cancel).start()
    events: list[dict] = []
    lock = threading.Lock()

    def record(e):
        with lock:
            events.append(e)

    run_mod.fetch_sources(cfg, on_progress=record, cancel=token)

    streamed = [r for e in events if e.get("event") == "source"
                for r in (e.get("found") or [])]
    assert streamed, "partial results were streamed before the stop"
    assert len(streamed) == len(calls)
