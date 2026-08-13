"""tests.test_pipeline_concurrency — Phase 1 concurrency (M1).

The crawl fetches sources in parallel, one isolated Http per source. These
tests pin the three guarantees that matter, fully offline (fake sources + a
fake Http, no network, no proxy):

- concurrent output is byte-for-byte identical to sequential (same records,
  same order — so dedupe/merge downstream stays deterministic);
- it is actually faster than sequential;
- one slow/crashing source never sinks the others (isolation).
"""

from __future__ import annotations

import argparse
import time
from collections import OrderedDict

import pytest

from core.config import build_config
import pipeline.run as run_mod


class _FakeHttp:
    """No-op stand-in so workers never touch the network or the proxy."""

    def __init__(self, cfg, detect=True):
        self.detect = detect

    def close(self):
        pass


def _cfg_with_fakes(names):
    cfg = build_config(argparse.Namespace())
    cfg.sources_enabled = {n: True for n in names}
    return cfg


def _make_sources(names, delay=0.0, boom=()):
    src = OrderedDict()
    for i, n in enumerate(names):
        def _fn(cfg, http, _n=n, _i=i):
            if delay:
                time.sleep(delay)
            if _n in boom:
                raise RuntimeError(f"{_n} exploded")
            return [{"title": f"{_n} job", "url": f"https://{_n}.test/{_i}"}]
        src[n] = _fn
    return src


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(run_mod, "Http", _FakeHttp)
    monkeypatch.setattr(run_mod, "_record_source", lambda *a, **k: None)


def test_concurrent_matches_sequential(monkeypatch):
    names = ["a", "b", "c", "d"]
    monkeypatch.setattr(run_mod, "SOURCES", _make_sources(names))
    cfg = _cfg_with_fakes(names)

    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 1)
    seq = run_mod.fetch_sources(cfg)
    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 4)
    conc = run_mod.fetch_sources(cfg)

    assert seq == conc                              # identical records AND order
    assert [r["source"] for r in conc] == names     # source tag + order kept


def test_concurrent_is_faster(monkeypatch):
    names = [f"s{i}" for i in range(5)]
    delay = 0.15
    monkeypatch.setattr(run_mod, "SOURCES", _make_sources(names, delay=delay))
    cfg = _cfg_with_fakes(names)

    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 1)
    t = time.perf_counter()
    run_mod.fetch_sources(cfg)
    seq_t = time.perf_counter() - t

    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 5)
    t = time.perf_counter()
    run_mod.fetch_sources(cfg)
    conc_t = time.perf_counter() - t

    assert seq_t > delay * 4        # ~5*0.15 = 0.75s sequential
    assert conc_t < seq_t / 2       # parallel collapses to ~one delay


def test_one_bad_source_does_not_sink_the_others(monkeypatch):
    names = ["ok1", "boom", "ok2"]
    monkeypatch.setattr(run_mod, "SOURCES", _make_sources(names, boom={"boom"}))
    cfg = _cfg_with_fakes(names)
    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 3)

    raw = run_mod.fetch_sources(cfg)

    assert {r["source"] for r in raw} == {"ok1", "ok2"}
    assert len(raw) == 2


def test_fetch_sources_emits_per_source_progress(monkeypatch):
    """M3: a start event with the total, then one event per source with its
    status/count — the payload the run dialog streams."""
    import threading
    names = ["ok1", "boom", "ok2"]
    monkeypatch.setattr(run_mod, "SOURCES", _make_sources(names, boom={"boom"}))
    cfg = _cfg_with_fakes(names)
    monkeypatch.setattr(run_mod, "_source_concurrency", lambda: 3)

    lock = threading.Lock()
    events: list = []

    def record(e):
        with lock:
            events.append(e)

    run_mod.fetch_sources(cfg, on_progress=record)

    starts = [e for e in events if e.get("event") == "start"]
    src = {e["source"]: e for e in events if e.get("event") == "source"}
    assert starts and starts[0]["total"] == 3
    assert set(src) == set(names)
    assert src["ok1"]["status"] == "done" and src["ok1"]["records"] == 1
    assert src["boom"]["status"] == "error" and src["boom"]["records"] == 0
