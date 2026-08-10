"""api.metrics — in-process request metrics (Sprint 06, Track C4).

A tiny, thread-safe, process-local tracker: total request count, 5xx error
count, and a bounded sliding window of latencies. ``snapshot()`` derives
avg/p95 latency and error rate for the admin dashboard. Values reset on
process restart — enough for a private beta (a production build would use a
metrics store like Prometheus).

The middleware in :mod:`api.app` calls ``metrics.record(...)`` for every
request; tests call ``metrics.reset()`` for isolation.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from statistics import median


class _RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.errors = 0
        self._latencies: deque[float] = deque(maxlen=1000)

    def record(self, status_code: int, elapsed: float) -> None:
        """Record one request outcome (status code + elapsed seconds)."""
        with self._lock:
            self.total += 1
            if status_code >= 500:
                self.errors += 1
            self._latencies.append(elapsed)

    def snapshot(self) -> dict:
        """Current counts + derived latency/error stats, or zeros if idle."""
        with self._lock:
            lat = list(self._latencies)
            total, errors = self.total, self.errors
        sorted_lat = sorted(lat)
        avg = (sum(lat) / len(lat) * 1000) if lat else 0.0
        if lat:
            idx = max(0, int(len(sorted_lat) * 0.95) - 1)
            p95 = sorted_lat[idx] * 1000
        else:
            p95 = 0.0
        return {
            "requests": total,
            "errors": errors,
            "error_rate": round(errors / total, 4) if total else 0.0,
            "avg_latency_ms": round(avg, 1),
            "p95_latency_ms": round(p95, 1),
            "median_latency_ms": round(median(lat) * 1000, 1) if lat else 0.0,
        }

    def reset(self) -> None:
        with self._lock:
            self.total = 0
            self.errors = 0
            self._latencies.clear()


metrics = _RequestMetrics()
