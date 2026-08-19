#!/usr/bin/env python3
"""Pytest bootstrap: make the aggregator package importable.

Allows the tests to be run from anywhere (``pytest`` from the repo root, the
astra/ dir, or an editor) by putting the package directory on
``sys.path`` — so future test files don't each need the manual
``sys.path.insert`` dance. Also flags the test environment so the API skips
starting background threads (e.g. the weekly-digest fallback scheduler).
"""
import os
import sys

os.environ.setdefault("ASTRA_TESTING", "1")

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)


# ---------------------------------------------------------------------------
# Close every engine a test opens, before the temporary directory holding its
# database is removed.
#
# On Linux an open file can still be unlinked, so a test that leaks a
# SQLAlchemy engine tears down perfectly and nothing is ever noticed. Windows
# refuses to delete a file any process still holds open, so exactly the same
# tests die in teardown with `PermissionError: [WinError 32] ... being used by
# another process` — after they have already PASSED. Eight of them did.
#
# Patching the one factory everything funnels through (`init_db` calls it too)
# covers the whole suite at once, and keeps working for tests not yet written.
#
# The disposal is a HOOK, not the fixture's own teardown, and that distinction
# is the entire fix. An autouse fixture is set up before the test's own
# `tmp_path`/TemporaryDirectory fixture, so it is finalised AFTER it — by which
# point the directory removal has already run and already failed.
# `pytest_runtest_teardown(tryfirst=True)` runs ahead of every fixture
# finaliser, which is the only point where the engines are closed but the
# directory is still there.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402

_OPEN_ENGINES = []


@pytest.fixture(autouse=True)
def _track_engines(monkeypatch):
    try:
        import db.init as dbinit
    except Exception:
        # Autouse means EVERY test runs this, including ones that touch no
        # database at all. Importing db.init pulls in SQLAlchemy, so a hard
        # import here would turn "sqlalchemy is not installed" into a failure
        # of the entire suite rather than of the tests that actually need it.
        return

    real = dbinit.create_engine_and_base

    def tracking(*args, **kwargs):
        engine = real(*args, **kwargs)
        _OPEN_ENGINES.append(engine)
        return engine

    monkeypatch.setattr(dbinit, "create_engine_and_base", tracking)


# The directory pytest was started from. Captured at import, before any test
# has had the chance to chdir out of it.
_ORIGINAL_CWD = os.getcwd()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    while _OPEN_ENGINES:
        try:
            _OPEN_ENGINES.pop().dispose()
        except Exception:
            pass

    # Windows cannot remove a directory that is any process's current working
    # directory, and `monkeypatch.chdir(tmp)` into a TemporaryDirectory is
    # undone only when the monkeypatch fixture finalises — which is AFTER the
    # fixture owning the directory has already tried, and failed, to delete it.
    # Stepping out here, ahead of every finaliser, is what makes that removal
    # possible. monkeypatch then restores the same path again, harmlessly.
    try:
        if os.getcwd() != _ORIGINAL_CWD:
            os.chdir(_ORIGINAL_CWD)
    except OSError:
        # The CWD can already be gone; chdir back regardless of why.
        os.chdir(_ORIGINAL_CWD)
