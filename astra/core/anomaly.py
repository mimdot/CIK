"""core.anomaly — rolling API-metrics anomaly detector (Sprint 09, Track B4).

The request middleware feeds every response into a module-level :class:`History`
(one 60s bucket: request count, 5xx count, cumulative latency). The pure
:func:`detect` function compares the latest bucket against the rolling
baseline (previous ``WINDOW_SLOTS`` buckets) and flags:

  * **5xx-spike** — current 5xx count is far above the window baseline;
  * **latency-spike** — current-minute average latency is many std above the
    window average.

``snapshot(run_alerts=True)`` also forwards each new anomaly through
``core.notify.notify_ops`` (debounced 1/hour per metric). Polling/admin GETs
use ``run_alerts=False`` for a side-effect-free read. All call paths are
best-effort and never raise.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

from core.notify import notify_ops

log = logging.getLogger("astra")

SLOT_S = 60             # one bucket per minute
WINDOW_SLOTS = 60       # 60 minutes of baseline
ERROR_Z = 2.5           # 5xx z-score at which a minute counts as a spike
MIN_ERRORS = 5          # ... and at least this many absolute 5xx responses
LAT_Z = 2.5             # latency z-score
MIN_LATENCY_MS = 800    # absolute latency floor before we care (ms)
DEBOUNCE_S = 3600       # one alert per metric per hour

Bucket = Tuple[int, int, int, float]  # (bucket_ts, requests, errors, lat_sum)


class History:
    """Thread-safe rolling window of per-minute request buckets."""

    def __init__(self, slot_s: int = SLOT_S,
                 window_slots: int = WINDOW_SLOTS) -> None:
        self.slot_s = slot_s
        self._slots: deque[Bucket] = deque(maxlen=window_slots)
        self._lock = threading.Lock()

    @property
    def _now_bucket(self) -> int:
        return int(time.time() // self.slot_s)

    def record(self, status_code: int, elapsed_s: float) -> None:
        """Record one response into the current minute bucket."""
        bucket = self._now_bucket
        with self._lock:
            if not self._slots or self._slots[-1][0] != bucket:
                self._slots.append((bucket, 0, 0, 0.0))
            b, reqs, errs, lat = self._slots[-1]
            self._slots[-1] = (b, reqs + 1,
                               errs + (1 if status_code >= 500 else 0),
                               lat + elapsed_s * 1000.0)

    def seed_bucket(self, requests: int, errors: int,
                    latency_ms: float = 0.0, count: int = 1,
                    ts: Optional[int] = None) -> None:
        """Insert ``count`` baseline buckets (test/seed helper)."""
        bucket = ts if ts is not None else self._now_bucket
        with self._lock:
            for _ in range(count):
                self._slots.append((bucket, requests, errors,
                                    latency_ms * requests))
                bucket += self.slot_s

    def snapshot(self) -> List[Bucket]:
        with self._lock:
            return [b for b in self._slots]

    def reset(self) -> None:
        with self._lock:
            self._slots.clear()


# shared live state (fed by the MetricsMiddleware)
_history = History()


def submit(status_code: int, elapsed_s: float) -> None:
    """Middleware hook: record one response."""
    try:
        _history.record(status_code, elapsed_s)
    except Exception as exc:
        log.warning("anomaly record failed: %s", exc)


def detect(slots: List[Bucket]) -> List[Dict[str, Any]]:
    """Pure anomaly detection over an ordered (oldest→newest) bucket list.

    Returns a list of anomaly dicts (each has ``kind``, ``ts``, ``id``,
    ``message``, plus metric-specific fields). Empty list when healthy.
    """
    if not slots:
        return []
    if len(slots) < 5:
        return []
    baseline = slots[:-1]
    latest = slots[-1]
    _, reqs, errs, lat = latest
    anomalies: List[Dict[str, Any]] = []

    # -- 5xx spike -------------------------------------------------------
    b_errs = [b[2] for b in baseline]
    b_reqs = [b[1] for b in baseline]
    mean_err = mean(b_errs) if b_errs else 0.0
    std_err = pstdev(b_errs) if len(b_errs) > 1 else 0.0
    base_err_rate = (sum(b_errs) / sum(b_reqs)) if sum(b_reqs) else 0.0
    err_rate = (errs / reqs) if reqs else 0.0
    z_err = (errs - mean_err) / std_err if std_err else 0.0
    spikes = (errs >= MIN_ERRORS and
              (z_err >= ERROR_Z or
               (std_err == 0.0 and errs > sum(b_errs))))
    if spikes:
        anomalies.append({
            "kind": "5xx-spike",
            "ts": latest[0],
            "value": errs,
            "baseline": round(mean_err, 2),
            "rate": round(err_rate, 4),
            "rate_baseline": round(base_err_rate, 4),
            "z": round(z_err, 2),
            "message": (f"5xx spike: {errs} errors in one minute vs "
                       f"{round(mean_err, 1)}/min baseline"),
        })

    # -- latency spike -----------------------------------------------------
    b_lat = [(b[3] / b[1]) if b[1] else 0.0 for b in baseline]
    mean_lat = mean(b_lat)
    std_lat = pstdev(b_lat) if len(b_lat) > 1 else 0.0
    lat_ms = (lat / reqs) if reqs else 0.0
    z_lat = (lat_ms - mean_lat) / std_lat if std_lat else 0.0
    if reqs and lat_ms > MIN_LATENCY_MS and (
            (std_lat > 0 and z_lat >= LAT_Z) or
            (std_lat == 0.0 and mean_lat and lat_ms > mean_lat * 3)):
        anomalies.append({
            "kind": "latency-spike",
            "ts": latest[0],
            "value": round(lat_ms, 1),
            "expected": round(mean_lat, 1),
            "z": round(z_lat, 2),
            "message": (f"latency spike {round(lat_ms, 1)}ms vs "
                        f"{round(mean_lat, 1)}ms baseline"),
        })

    for a in anomalies:
        a["id"] = f"{a['kind']}:{a['ts']}"
    return anomalies


_debounce_seen: Dict[str, float] = {}
_debounce_lock = threading.Lock()


def _debounce(anomaly_id: str) -> bool:
    now = time.time()
    with _debounce_lock:
        if now - _debounce_seen.get(anomaly_id, 0.0) < DEBOUNCE_S:
            return False
        _debounce_seen[anomaly_id] = now
        return True


def snapshot(run_alerts: bool = False) -> Dict[str, Any]:
    """Aggregate view of the rolling history + detected anomalies."""
    slots = _history.snapshot()
    anomalies = detect(slots)
    if run_alerts:
        for a in anomalies:
            if _debounce(a["id"]):
                try:
                    notify_ops(a["message"], tags=["AnomalyAPI"])
                except Exception as exc:
                    log.warning("anomaly alert failed: %s", exc)

    total_reqs = sum(b[1] for b in slots)
    total_errs = sum(b[2] for b in slots)
    lat_total = sum(b[3] for b in slots)
    current: Optional[Dict[str, Any]] = None
    if slots:
        last = slots[-1]
        current = {"ts": last[0], "requests": last[1], "errors": last[2],
                   "latency_ms": round(last[3] / last[1], 1)
                   if last[1] else 0.0}
    return {
        "slot_s": SLOT_S,
        "slots": [{"ts": b[0], "requests": b[1], "errors": b[2],
                   "latency_ms": round(b[3] / b[1], 1) if b[1] else 0.0}
                  for b in slots[-12:]],
        "current": current,
        "summaries": {
            "requests": total_reqs,
            "errors": total_errs,
            "error_rate": round(total_errs / total_reqs, 4)
            if total_reqs else 0.0,
            "avg_latency_ms": round(lat_total / total_reqs, 1)
            if total_reqs else 0.0,
        },
        "anomalies": anomalies,
    }


# test/seed helpers -----------------------------------------------------------
def reset() -> None:
    _history.reset()
    with _debounce_lock:
        _debounce_seen.clear()


def seed(requests: int, errors: int, latency_ms: float = 0.0,
         count: int = 1, ts: Optional[int] = None) -> None:
    _history.seed_bucket(requests, errors, latency_ms, count, ts)