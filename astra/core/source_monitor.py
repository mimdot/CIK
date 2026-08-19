"""core.source_monitor — source-availability health (Sprint 09, Track B1).

The pipeline records, per source, the number of raw records each run pulled
(``record_run``) and any raise during fetch (``record_error``). ``check_drift``
compares the latest run against a rolling baseline (last ``WINDOW`` runs) and
alerts ops via ``core.notify`` when a value drifts (|z| > DRIFT_Z) or the
source has errored MAX_ERRORS consecutive times. Alerts are debounced to one
per source per hour so a noisy source cannot page ops repeatedly.

State lives in Redis (rolling list per source) with an in-memory fallback,
mirroring ``core.ratelimit``. Everything is best-effort and never raises, so
monitoring cannot break the pipeline. Tests can seed rows with
``record_run``/``record_error`` and assert on the health snapshot.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from core.cache import _get_redis
from core.notify import notify_ops

log = logging.getLogger("astra")

WINDOW = 30          # rolling baseline window in runs
DRIFT_Z = 2.5        # |z| above which the latest run is an anomaly
MAX_ERRORS = 3       # consecutive failures that alert ops
DEBOUNCE_S = 3600    # one alert per source per hour

_MEMORY: Dict[str, Dict[str, Any]] = {}
_MEM_LOCK = threading.Lock()


def _key(source: str) -> str:
    return f"sourcehealth:{source}"


def _read_window(source: str) -> List[Dict[str, Any]]:
    r = _get_redis()
    if r is not None:
        try:
            raw = r.lrange(_key(source), 0, -1)
            return [json.loads(x) for x in raw]
        except Exception:
            pass
    with _MEM_LOCK:
        return list(_MEMORY.get(source, {}).get("runs", []))


def _push_run(source: str, entry: Dict[str, Any]) -> None:
    r = _get_redis()
    if r is not None:
        try:
            key = _key(source)
            pipe = r.pipeline()
            pipe.rpush(key, json.dumps(entry))
            pipe.ltrim(key, -WINDOW, -1)
            pipe.expire(key, DEBOUNCE_S * 24)
            pipe.execute()
            return
        except Exception:
            pass
    with _MEM_LOCK:
        runs = _MEMORY.setdefault(source, {}).setdefault(
            "runs", deque(maxlen=WINDOW))
        runs.append(entry)


def record_run(source: str, raw_records: int, kept: Optional[int] = None,
               duration_s: Optional[float] = None) -> None:
    """Record a successful fetch of ``raw_records`` items for a source."""
    _push_run(source, {"n": int(raw_records), "err": 0,
                        "kept": kept, "dur": duration_s,
                        "ts": time.time()})


def record_error(source: str) -> None:
    """Record that a source's fetch raised."""
    _push_run(source, {"n": 0, "err": 1, "ts": time.time()})


def _successful_values(runs: List[Dict[str, Any]]) -> List[int]:
    return [r["n"] for r in runs if not r.get("err", 0)]


def source_health() -> List[Dict[str, Any]]:
    """Per-source health snapshot using the rolling baseline.

    One entry per source: ``source``, ``runs`` (window size), ``errors``,
    ``last_result``, ``mean``/``std`` of successful runs, ``zscore`` of the
    latest run (None when no baseline or no delta), and ``drift``. A source
    with no recorded run is excluded.
    """
    health: List[Dict[str, Any]] = []
    for source in sorted(_known_sources()):
        runs = _read_window(source)
        if not runs:
            continue
        values = _successful_values(runs)
        last = runs[-1]
        mean = round(statistics.mean(values), 2) if values else None
        std = (statistics.pstdev(values)
               if len(values) > 1 else 0.0)
        n = last.get("n") if not last.get("err", 0) else None
        drift = False
        zscore: Optional[float] = None
        if n is not None and values:
            if std:
                z = abs(n - mean) / std
                zscore = round(z, 2)
                drift = z > DRIFT_Z
            elif values and all(v == mean for v in values):
                delta = abs(n - mean) if mean else n
                drift = delta > (mean * 0.5) if mean else n > 0
        else:
            consecutive = all(r.get("err", 0) for r in runs[-MAX_ERRORS:]
                              ) if len(runs) >= MAX_ERRORS else False
            drift = consecutive
        health.append({
            "source": source,
            "runs": len(runs),
            "errors": sum(1 for r in runs if r.get("err", 0)),
            "last_result": last.get("n"),
            "mean": mean,
            "std": round(std, 2) if std else None,
            "zscore": zscore,
            "drift": bool(drift),
            "updated_ts": round(last.get("ts", 0), 3),
        })
    return health


def _known_sources() -> List[str]:
    r = _get_redis()
    if r is not None:
        try:
            keys = r.keys("sourcehealth:*")
            return sorted({k.split(":", 1)[1] for k in keys if "alert" not in k}) \
                   + _memory_sources()
        except Exception:
            pass
    return _memory_sources()


def _memory_sources() -> List[str]:
    with _MEM_LOCK:
        return list(_MEMORY.keys())


def _debounce_due(source: str) -> bool:
    """True when alerts for this source are currently allowed."""
    now = time.time()
    r = _get_redis()
    if r is not None:
        try:
            prev = r.get(_key(f"alert:{source}"))
            last = float(prev) if prev else 0.0
            if now - last < DEBOUNCE_S:
                return False
            r.set(_key(f"alert:{source}"), str(now), ex=DEBOUNCE_S * 2)
            return True
        except Exception:
            pass
    with _MEM_LOCK:
        last = _MEMORY.get(source, {}).get("last_alert", 0.0)
        if now - last < DEBOUNCE_S:
            return False
        _MEMORY.setdefault(source, {})["last_alert"] = now
        return True


def check_drift() -> List[Dict[str, Any]]:
    """Alert on drifted/erroring sources; returns the new alert payloads."""
    alerts: List[Dict[str, Any]] = []
    for entry in source_health():
        if not entry["drift"]:
            continue
        source = entry["source"]
        if not _debounce_due(source):
            continue
        reason = (f"raw count {entry['last_result']} deviated from baseline "
                  f"mean {entry['mean']} (z={entry['zscore']})"
                  if entry["zscore"] is not None
                  else f"{entry['errors']} consecutive errors")
        _dispatch(f"Source health: {source} drifted — {reason}")
        alerts.append({"source": source, "reason": reason,
                       "zscore": entry["zscore"],
                       "last_result": entry["last_result"],
                       "mean": entry["mean"]})
    return alerts


def _dispatch(message: str) -> None:
    try:
        notify_ops(message, tags=["SourceHealthDrift"])
    except Exception as exc:  # defensive: never propagate
        log.warning("source_monitor: dispatch failed: %s", exc)