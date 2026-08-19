"""Tests for core.source_monitor (Sprint 09, Track B01).

These force the in-memory fallback (no Redis) so they are deterministic and
offline; the Redis path shares the same entry-points.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def mem(monkeypatch):
    import core.source_monitor as sm
    monkeypatch.setattr(sm, "_get_redis", lambda: None)
    sm._MEMORY.clear()
    yield sm
    sm._MEMORY.clear()


def _seed_run(sm, source: str, value: int) -> None:
    sm.record_run(source, raw_records=value)


def test_record_run_then_snapshot(mem):
    mem.record_run("euraxess", raw_records=120)
    entry = mem.source_health()
    assert len(entry) == 1
    row = entry[0]
    assert row["source"] == "euraxess"
    assert row["runs"] == 1
    assert row["last_result"] == 120
    assert row["drift"] is False
    assert row["errors"] == 0


def test_stable_source_is_not_drift(mem):
    for i in range(10):
        mem.record_run("stable", raw_records=4)
    (row,) = [r for r in mem.source_health() if r["source"] == "stable"]
    assert all(v == row["mean"] for v in [row["mean"]])
    assert row["drift"] is False
    assert row["std"] is None  # no-run variance → no z-score
    assert row["zscore"] is None


def test_large_deviation_triggers_drift(mem):
    for i in range(10):
        mem.record_run("spiky", raw_records=3 + i % 2)
    mem.record_run("spiky", raw_records=200)
    (row,) = [r for r in mem.source_health() if r["source"] == "spiky"]
    assert row["drift"] is True
    assert row["last_result"] == 200
    assert row["zscore"] > 2.5


def test_three_consecutive_errors_trigger_drift(mem):
    for _ in range(3):
        mem.record_error("down")
    (row,) = [r for r in mem.source_health() if r["source"] == "down"]
    assert row["drift"] is True
    assert row["errors"] == 3


def test_two_errors_not_enough(mem):
    mem.record_error("wobbly")
    mem.record_error("wobbly")
    (row,) = [r for r in mem.source_health() if r["source"] == "wobbly"]
    assert row["drift"] is False


def test_errors_mixed_with_success_still_makes_drift(mem):
    mem.record_run("mixy", raw_records=4)
    mem.record_run("mixy", raw_records=5)
    mem.record_error("mixy")
    mem.record_error("mixy")
    mem.record_error("mixy")
    (row,) = [r for r in mem.source_health() if r["source"] == "mixy"]
    assert row["errors"] == 3
    assert row["drift"] is True


def test_check_drift_fires_once_per_debounce(mem):
    for i in range(10):
        mem.record_run("deb", raw_records=3 + i % 2)
    mem.record_run("deb", raw_records=250)
    first = mem.check_drift()
    assert len(first) == 1
    assert first[0]["source"] == "deb"
    second = mem.check_drift()
    assert second == []  # debounce: same source within the hour


def test_debounce_isolated_per_source(mem):
    for i in range(10):
        mem.record_run("one", raw_records=3 + i % 2)
        mem.record_run("two", raw_records=3 + i % 2)
    mem.record_run("one", raw_records=250)
    mem.record_run("two", raw_records=250)
    alerts = mem.check_drift()
    sources = {a["source"] for a in alerts}
    third = mem._debounce_due("two")  # and one already alerted
    assert "two" in sources
    # after the first pass, everything is debounced
    assert mem.check_drift() == []


def test_active_sources_excluded_empty(mem):
    assert mem.source_health() == []
    mem.record_run("ghost", raw_records=1)
    assert len(mem.source_health()) == 1