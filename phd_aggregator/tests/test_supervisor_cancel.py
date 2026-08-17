"""tests.test_supervisor_cancel — a supervisor search can be stopped and watched.

A supervisor search runs for minutes across field x country pairs. Before this
it could be neither cancelled nor observed: the dialog showed a spinner and an
elapsed counter, which look identical whether the engine is working or wedged.

Two behaviours are pinned here:
  * cancelling stops it between pairs, and KEEPS what was already saved —
    a cancelled run is a shortened one, not a discarded one
  * progress is emitted per pair in the same shape the opportunities engine
    uses, so the run dialog renders it with machinery it already has
"""

from __future__ import annotations

import pytest

from cli import commands


class _Token:
    """Cancels after the Nth poll, so a run stops mid-sweep like a real one."""

    def __init__(self, after: int = 1):
        self.after = after
        self.polls = 0

    def is_cancelled(self) -> bool:
        self.polls += 1
        return self.polls > self.after


@pytest.fixture()
def fake_sweep(monkeypatch, tmp_path):
    """Make sync_supervisors' inner work a no-op so the loop is what is tested."""
    import phd_aggregator as P

    monkeypatch.setattr(P, "list_field_profiles", lambda: ["astronomy", "biology"])
    monkeypatch.setattr(P, "load_field_profile", lambda name: {"name": name})
    # The per-pair body raises immediately; the loop treats that as a failed
    # pair and carries on, which is all these tests need it to do.
    monkeypatch.setattr(P, "build_config",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub")))
    monkeypatch.setattr(commands, "_session", lambda url: _FakeSession())
    monkeypatch.setattr(commands, "SupervisorRepo", lambda s: object())
    return None


class _FakeSession:
    def commit(self):
        pass

    def close(self):
        pass


def test_progress_reports_every_pair(fake_sweep):
    events = []
    upserted, _ = commands.sync_supervisors(
        ["Germany", "France"], field=None, quick=True,
        on_progress=events.append)

    start = [e for e in events if e.get("event") == "start"]
    pairs = [e for e in events if e.get("event") == "source"]
    assert start and start[0]["total"] == 4, "2 fields x 2 countries"
    assert len(pairs) == 4, "every pair reports, including the ones that failed"
    # Same keys the opportunities engine emits, so the UI needs no new shape.
    assert set(pairs[0]) >= {"event", "source", "status", "records", "duration"}
    assert " · " in pairs[0]["source"], "labelled field · country"


def test_cancel_stops_the_sweep_early(fake_sweep):
    events = []
    commands.sync_supervisors(
        ["Germany", "France"], field=None, quick=True,
        cancel=_Token(after=1), on_progress=events.append)

    pairs = [e for e in events if e.get("event") == "source"]
    assert len(pairs) < 4, "cancelling must stop the sweep, not run it to the end"


def test_cancel_before_the_first_pair_does_nothing_harmful(fake_sweep):
    events = []
    upserted, total = commands.sync_supervisors(
        ["Germany"], field=None, quick=True,
        cancel=_Token(after=0), on_progress=events.append)

    assert [e for e in events if e.get("event") == "source"] == []
    assert (upserted, total) == (0, 0)


def test_no_cancel_token_runs_every_pair(fake_sweep):
    """The CLI passes no token; it must sweep everything as before."""
    events = []
    commands.sync_supervisors(["Germany", "France"], field=None, quick=True,
                              on_progress=events.append)
    assert len([e for e in events if e.get("event") == "source"]) == 4


def test_progress_is_optional(fake_sweep):
    """The CLI passes no callback either — nothing may require one."""
    upserted, total = commands.sync_supervisors(["Germany"], field=None, quick=True)
    assert (upserted, total) == (0, 0)
