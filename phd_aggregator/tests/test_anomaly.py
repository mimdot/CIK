"""tests.test_anomaly — Sprint 09, Track B4 (rolling API-metrics anomaly
detector). Exercises the pure ``detect`` function over seeded ``History``
buckets: 5xx spikes, latency spikes, healthy silence, baseline-required
guards, and the debounce on re-alerting.
"""

from __future__ import annotations

import pytest

from core import anomaly
from core.anomaly import History, detect


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(anomaly, "_debounce_seen", {})
    return None


def _healthy(history):
    for i in range(6):
        history.seed_bucket(requests=10, errors=0, latency_ms=80, ts=1 + i)


def test_empty_history_is_healthy():
    assert detect([]) == []


def test_short_window_no_false_positive():
    h = History()
    h.seed_bucket(10, 0, 80, count=3)
    assert detect(h.snapshot()) == []


def test_no_anomaly_on_steady_traffic():
    h = History()
    _healthy(h)
    h.seed_bucket(10, 0, 80, ts=7)
    assert detect(h.snapshot()) == []


def test_5xx_spike_detected():
    h = History()
    _healthy(h)
    h.seed_bucket(requests=20, errors=15, latency_ms=80, ts=7)
    found = {a["kind"] for a in detect(h.snapshot())}
    assert "5xx-spike" in found


def test_latency_spike_detected():
    h = History()
    for i in range(6):
        h.seed_bucket(10, 0, 60, ts=1 + i)
    h.seed_bucket(requests=5, errors=0, latency_ms=2500, ts=10)
    found = {a["kind"] for a in detect(h.snapshot())}
    assert "latency-spike" in found


def test_small_error_blip_is_not_a_spike():
    h = History()
    _healthy(h)
    h.seed_bucket(requests=20, errors=2, latency_ms=90, ts=8)
    # 2 < MIN_ERRORS=5 -> healthy even though the rate is elevated
    assert detect(h.snapshot()) == []


def test_anomaly_carries_ids_and_ts():
    h = History()
    _healthy(h)
    h.seed_bucket(requests=20, errors=12, latency_ms=100, ts=30)
    out = detect(h.snapshot())
    assert out
    for a in out:
        assert a["id"] == f"{a['kind']}:{a['ts']}"


def test_snapshot_shape_and_current(monkeypatch):
    h = History()
    _healthy(h)
    monkeypatch.setattr(anomaly, "_history", h)
    data = anomaly.snapshot()
    assert data["summaries"]["requests"] == 60
    assert data["current"] == {"ts": 6, "requests": 10, "errors": 0,
                               "latency_ms": 80.0}
    assert set(data) >= {"slots", "current", "summaries", "anomalies"}


def test_snapshot_run_alerts_debounces(monkeypatch):
    h = History()
    _healthy(h)
    h.seed_bucket(requests=20, errors=15, latency_ms=100, ts=40)
    monkeypatch.setattr(anomaly, "_history", h)
    notified = []
    monkeypatch.setattr(anomaly, "notify_ops",
                        lambda msg, tags=None: notified.append(msg))
    data1 = anomaly.snapshot(run_alerts=True)
    assert data1["anomalies"]
    assert len(notified) == len(data1["anomalies"])
    data2 = anomaly.snapshot(run_alerts=True)
    assert data2["anomalies"]
    assert len(notified) == len(data1["anomalies"])  # debounced, no re-send


def test_middleware_record_path(monkeypatch):
    monkeypatch.setattr(anomaly, "_history", History())
    anomaly.submit(200, 0.01)
    anomaly.submit(503, 0.02)
    slots = anomaly._history.snapshot()
    assert slots[-1][1] == 2
    assert slots[-1][2] == 1