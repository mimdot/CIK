#!/usr/bin/env python3
"""A database created by an older version must still be writable today.

The bug: ``supervisors.fit_explanation`` was added to the model (and to an
Alembic revision) but never reached databases created before it, because
``Base.metadata.create_all`` only creates missing TABLES — it never adds a
column to a table that already exists, and the desktop app never runs Alembic
at all.

The result was indistinguishable from an empty search. The supervisor run found
89 real candidates for Germany, failed to upsert every one of them with
``no such column: supervisors.fit_explanation``, swallowed each failure as a
log warning, and reported "completed, 0 records".
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from db.init import init_db, reconcile_columns
from db.models import Base


@pytest.fixture
def legacy_db():
    """A database whose supervisors table predates fit_explanation."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.db"
        engine = init_db(f"sqlite:///{path}")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE supervisors DROP COLUMN fit_explanation"))
        engine.dispose()
        cols = {r[1] for r in sqlite3.connect(path).execute(
            "PRAGMA table_info(supervisors)")}
        assert "fit_explanation" not in cols, "fixture did not create the drift"
        yield path


def test_create_all_alone_does_not_repair_an_existing_table(legacy_db):
    """Pins WHY this is needed: create_all is not a migration."""
    from db.init import create_engine_and_base
    engine = create_engine_and_base(f"sqlite:///{legacy_db}")
    Base.metadata.create_all(engine)
    cols = {r[1] for r in sqlite3.connect(legacy_db).execute(
        "PRAGMA table_info(supervisors)")}
    assert "fit_explanation" not in cols


def test_init_db_adds_the_missing_column(legacy_db):
    init_db(f"sqlite:///{legacy_db}")
    cols = {r[1] for r in sqlite3.connect(legacy_db).execute(
        "PRAGMA table_info(supervisors)")}
    assert "fit_explanation" in cols


def test_reconcile_reports_what_it_added(legacy_db):
    from db.init import create_engine_and_base
    engine = create_engine_and_base(f"sqlite:///{legacy_db}")
    added = reconcile_columns(engine)
    assert "supervisors.fit_explanation" in added


def test_reconcile_is_idempotent(legacy_db):
    init_db(f"sqlite:///{legacy_db}")
    from db.init import create_engine_and_base
    engine = create_engine_and_base(f"sqlite:///{legacy_db}")
    assert reconcile_columns(engine) == []


def test_a_supervisor_row_with_a_fit_explanation_round_trips(legacy_db):
    """The end the user cares about: results actually save and read back."""
    from sqlalchemy.orm import Session
    from db.models import Supervisor

    engine = init_db(f"sqlite:///{legacy_db}")
    with Session(engine) as session:
        session.add(Supervisor(source="openalex", name="A. Vidotto",
                               country="Netherlands", fit_score=89.2,
                               fit_explanation="topic overlap: exoplanets"))
        session.commit()
    with Session(engine) as session:
        row = session.query(Supervisor).filter_by(name="A. Vidotto").one()
    assert row.fit_explanation == "topic overlap: exoplanets"
