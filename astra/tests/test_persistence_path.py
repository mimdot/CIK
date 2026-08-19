#!/usr/bin/env python3
"""The save path, exercised end-to-end in-process.

The bug these exist for: ``run_pipeline_job`` finished a crawl, then hit
``NameError: name 'Session' is not defined`` on the very next line, because
``Session`` was imported function-locally at three other call sites but never
at module level nor inside this one. The broad ``except Exception`` around the
seeding block turned that into ``funnel["storage_error"]`` and a log warning,
so every run reported success while silently saving nothing.

Nothing caught it because every existing test of ``run_pipeline_job``
monkeypatched ``seed_from_json`` away and asserted only on taxonomy wiring —
the persistence path itself was never executed against a real database.

So these tests do the opposite: run the real save path against a real (temp)
SQLite DB and assert the rows are there and re-readable.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import tasks as tasks_module
from core.records import make_record
from db.init import init_db
from db.models import Opportunity


@pytest.fixture
def tmp_run(monkeypatch):
    """A temp cwd + temp DB, so a run writes nothing into the repo."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        monkeypatch.setattr("db.init.resolve_db_url",
                            lambda: f"sqlite:///{db_path}")
        monkeypatch.chdir(tmp)
        yield tmp, db_path


def _one_record():
    return make_record(
        title="PhD in Radio Astronomy",
        url="https://example.org/phd/1",
        short_description="radio astronomy interstellar medium",
        source="euraxess",
        institution="Test University",
        country="Netherlands",
    )


def _inject(records):
    """Patch pipeline_run to write the JSON the seeder reads, like the real one."""
    def fake_pipeline_run(cfg, only_sources=None, on_progress=None,
                          funnel=None, cancel=None, **kw):
        # Mirror the real pipeline: stamp the active field onto every record
        # before writing (pipeline/run.py), because the stored row's field is
        # what keeps a chemistry view from showing astronomy leftovers.
        stamped = [{**r, "field": r.get("field") or cfg.field_profile}
                   for r in records]
        with open(cfg.json_path, "w", encoding="utf-8") as fh:
            json.dump(stamped, fh)
        if funnel is not None:
            funnel["found"] = len(stamped)
        return stamped
    return fake_pipeline_run


# --- the regression -----------------------------------------------------------

def test_completed_run_actually_persists_records(tmp_run, monkeypatch):
    """A finished crawl must land in the database and be readable back.

    This is the assertion that was missing. Before the fix it failed with
    ``storage_error == "NameError: name 'Session' is not defined"`` and zero
    rows stored.
    """
    _tmp, db_path = tmp_run
    records = [_one_record()]
    monkeypatch.setattr(tasks_module, "pipeline_run", _inject(records))

    funnel: dict = {}
    captured: list[dict] = []
    count = tasks_module.run_pipeline_job(
        field="astronomy",
        on_progress=lambda ev: captured.append(ev),
    )

    assert count == 1
    # The run reported no storage problem...
    funnel_event = [e for e in captured if e.get("event") == "funnel"]
    assert funnel_event, "the run must emit a final funnel event"
    assert "storage_error" not in funnel_event[0], (
        f"save failed: {funnel_event[0].get('storage_error')}")
    assert funnel_event[0]["stored"] == 1

    # ...and the row is genuinely in the database, re-readable in a NEW session.
    engine = init_db(f"sqlite:///{db_path}")
    with Session(engine) as session:
        rows = session.scalars(select(Opportunity)).all()
    assert len(rows) == 1
    assert rows[0].title == "PhD in Radio Astronomy"
    assert rows[0].url == "https://example.org/phd/1"
    assert rows[0].field == "astronomy"


def test_session_is_importable_at_module_scope():
    """The direct guard against the exact regression: the name must resolve."""
    assert getattr(tasks_module, "Session", None) is Session


# --- the hardening ------------------------------------------------------------

def test_storage_failure_names_the_exception_type(tmp_run, monkeypatch):
    """A save failure must say WHAT failed, not just echo a bare message."""
    monkeypatch.setattr(tasks_module, "pipeline_run", _inject([_one_record()]))

    def boom(*a, **k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr("db.init.seed_from_json", boom)

    captured: list[dict] = []
    tasks_module.run_pipeline_job(field="astronomy",
                                  on_progress=lambda ev: captured.append(ev))

    funnel = [e for e in captured if e.get("event") == "funnel"][0]
    assert funnel["storage_error"] == "RuntimeError: database is locked"


def test_storage_failure_rescues_results_to_a_timestamped_file(tmp_run,
                                                               monkeypatch):
    """A completed crawl is never lost, even when the database refuses it.

    The pipeline's own JSON/CSV live at FIXED paths that the next run
    overwrites, so "it's still on disk" is only true until the user searches
    again. The rescue copy is timestamped and therefore durable.
    """
    records = [_one_record()]
    monkeypatch.setattr(tasks_module, "pipeline_run", _inject(records))
    monkeypatch.setattr("db.init.seed_from_json",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("disk on fire")))

    captured: list[dict] = []
    tasks_module.run_pipeline_job(field="astronomy",
                                  on_progress=lambda ev: captured.append(ev))

    funnel = [e for e in captured if e.get("event") == "funnel"][0]
    path = funnel.get("storage_rescue_path")
    assert path, "a failed save must report where the results were rescued to"
    assert os.path.isabs(path), "the user needs the full path, not a relative one"
    assert "rescue-" in os.path.basename(path)
    with open(path, encoding="utf-8") as fh:
        rescued = json.load(fh)
    assert len(rescued) == 1
    assert rescued[0]["title"] == "PhD in Radio Astronomy"


def test_successful_save_invalidates_the_cached_list(tmp_run, monkeypatch):
    """After a save the UI must read the NEW rows, not a stale cached list.

    This is the second half of "the list below may be out of date": the seeding
    block also owned cache invalidation, so the NameError skipped it too and the
    dashboard kept serving the previous field's cached page.
    """
    from core import cache
    monkeypatch.setattr(tasks_module, "pipeline_run", _inject([_one_record()]))

    cache.cache_opportunity_list([{"title": "stale row"}], "astronomy")
    assert cache.get_cached_opportunity_list("astronomy") is not None

    tasks_module.run_pipeline_job(field="astronomy")

    assert cache.get_cached_opportunity_list("astronomy") is None
