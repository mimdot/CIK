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

EVERY handle here is closed explicitly — engines through ``opened()``, raw
connections through ``columns()``. On Linux an open file can still be unlinked,
so leaking them costs nothing and the original version of this file did; on
Windows the temporary directory cannot be removed while anything holds the
database open, and the whole module errored out in teardown with WinError 32.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from db.init import create_engine_and_base, init_db, reconcile_columns
from db.models import Base


@contextmanager
def opened(path: Path, *, initialise: bool = True):
    """An engine on ``path`` that is always disposed."""
    url = f"sqlite:///{path}"
    engine = init_db(url) if initialise else create_engine_and_base(url)
    try:
        yield engine
    finally:
        engine.dispose()


def columns(path: Path, table: str) -> set[str]:
    """The column names of ``table``, without leaving the file open."""
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


@pytest.fixture
def legacy_db():
    """A database whose supervisors table predates fit_explanation."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.db"
        with opened(path) as engine:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE supervisors DROP COLUMN fit_explanation"))
        assert "fit_explanation" not in columns(path, "supervisors"), \
            "fixture did not create the drift"
        yield path


def test_create_all_alone_does_not_repair_an_existing_table(legacy_db):
    """Pins WHY this is needed: create_all is not a migration."""
    with opened(legacy_db, initialise=False) as engine:
        Base.metadata.create_all(engine)
    assert "fit_explanation" not in columns(legacy_db, "supervisors")


def test_init_db_adds_the_missing_column(legacy_db):
    with opened(legacy_db):
        pass
    assert "fit_explanation" in columns(legacy_db, "supervisors")


def test_reconcile_reports_what_it_added(legacy_db):
    with opened(legacy_db, initialise=False) as engine:
        assert "supervisors.fit_explanation" in reconcile_columns(engine)


def test_reconcile_is_idempotent(legacy_db):
    with opened(legacy_db):
        pass
    with opened(legacy_db, initialise=False) as engine:
        assert reconcile_columns(engine) == []


def test_a_supervisor_row_with_a_fit_explanation_round_trips(legacy_db):
    """The end the user cares about: results actually save and read back."""
    from sqlalchemy.orm import Session

    from db.models import Supervisor

    with opened(legacy_db) as engine:
        with Session(engine) as session:
            session.add(Supervisor(source="openalex", name="A. Vidotto",
                                   country="Netherlands", fit_score=89.2,
                                   fit_explanation="topic overlap: exoplanets"))
            session.commit()
        with Session(engine) as session:
            row = session.query(Supervisor).filter_by(name="A. Vidotto").one()
            assert row.fit_explanation == "topic overlap: exoplanets"


# ---------------------------------------------------------------------------
# NOT NULL columns. ``users.role`` is the one that bites: it is NOT NULL with a
# Python-side default, so the model carries a value but the DDL never does, and
# the first version of reconcile_columns refused it on sight. A database made
# before that column then could not log anybody in — "no such column:
# users.role" — with the reason buried in a log line nobody reads.
# ---------------------------------------------------------------------------
@pytest.fixture
def legacy_users_db():
    """A users table that predates `role`, holding one pre-existing account."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy_users.db"
        with opened(path) as engine:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users DROP COLUMN role"))
                # A row from the old world, with no role recorded anywhere.
                conn.execute(text(
                    "INSERT INTO users (email, hashed_password, "
                    "email_verified, created_at) VALUES ('old@example.com', "
                    "'x', 0, '2020-01-01 00:00:00')"))
        assert "role" not in columns(path, "users"), \
            "fixture did not create the drift"
        yield path


def test_not_null_column_with_a_default_is_added(legacy_users_db):
    with opened(legacy_users_db, initialise=False) as engine:
        assert "users.role" in reconcile_columns(engine)
        assert "role" in columns(legacy_users_db, "users")
        # And it stays done — a second pass finds nothing left to add.
        assert reconcile_columns(engine) == []


def test_the_pre_existing_row_is_backfilled_not_nulled(legacy_users_db):
    """The point of the DEFAULT: rows predating the column still get a value."""
    with opened(legacy_users_db):
        pass
    conn = sqlite3.connect(legacy_users_db)
    try:
        rows = list(conn.execute("SELECT email, role FROM users"))
    finally:
        conn.close()
    assert rows == [("old@example.com", "user")]


def test_login_shaped_query_works_after_the_upgrade(legacy_users_db):
    """The end the user cares about: the old account can still be read."""
    from sqlalchemy.orm import Session

    from db.models import User

    with opened(legacy_users_db) as engine:
        with Session(engine) as session:
            row = session.query(User).filter_by(email="old@example.com").one()
            assert row.role == "user"


def test_a_not_null_column_with_no_default_is_reported_not_guessed(caplog):
    """The honest half: nothing to backfill with means nothing is invented."""
    import logging

    from sqlalchemy import Column, Integer, MetaData, String, Table

    import db.init as dbinit

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nodefault.db"
        with opened(path, initialise=False) as engine:
            before = MetaData()
            Table("t", before, Column("id", Integer, primary_key=True))
            before.create_all(engine)

            # The same table, now with a NOT NULL column carrying no default.
            after = MetaData()
            Table("t", after, Column("id", Integer, primary_key=True),
                  Column("mandatory", String(16), nullable=False))

            class _ModelsWithoutADefault:
                metadata = after

            real, dbinit.Base = dbinit.Base, _ModelsWithoutADefault
            try:
                with caplog.at_level(logging.ERROR):
                    added = dbinit.reconcile_columns(engine)
            finally:
                dbinit.Base = real

        assert added == []
        assert "mandatory" in caplog.text
        assert "mandatory" not in columns(path, "t")


def test_a_backfilled_datetime_reads_back_through_the_orm():
    """A NOT NULL DateTime is backfilled as a literal — it must be readable.

    `utcnow()` returns an AWARE datetime while the column is naive. Rendering
    it with its "+00:00" offset writes a value SQLAlchemy's SQLite type then
    refuses to parse, so the column would be repaired and the table still
    unreadable — a subtler version of the bug being fixed.
    """
    from sqlalchemy.orm import Session

    from db.models import User

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy_dates.db"
        with opened(path) as engine:
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (email, hashed_password, role, "
                    "email_verified, created_at) VALUES ('d@example.com', "
                    "'x', 'user', 0, '2020-01-01 00:00:00')"))
                conn.execute(text("ALTER TABLE users DROP COLUMN created_at"))
        assert "created_at" not in columns(path, "users")

        with opened(path) as engine:        # init_db reconciles on the way in
            with Session(engine) as session:
                row = session.query(User).filter_by(email="d@example.com").one()
                assert row.created_at is not None
                assert row.created_at.tzinfo is None
