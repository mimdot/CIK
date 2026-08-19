"""tests.test_digest_jobs — Sprint 07, Track A3: the weekly digest jobs in
core.tasks. Uses an in-memory SQLite session factory and a stubbed email
sender so nothing leaves the test process.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from uuid import uuid4

from core import tasks
from db.models import Base, DigestPreference, EmailEvent, Opportunity, User, \
    UserProfileRow
from db.repositories import UserRepo


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    tasks._in_memory_jobs.clear()
    tasks._digest_run_day = None
    from core import cache
    cache.invalidate("")
    yield
    tasks._in_memory_jobs.clear()
    tasks._digest_run_day = None
    cache.invalidate("")


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def session_factory(session):
    return lambda: session


def _seed_profile(session, *, domain="astronomy", digest_email=None,
                  frequency="weekly", user_email=None):
    user = UserRepo(session).create(user_email or f"digest-{uuid4().hex[:8]}@example.com",
                                    "hash")
    row = UserProfileRow(
        user_id=user.id, domain=domain, subfield="interstellar medium",
        methods='["radio interferometry"]', tools='["python"]',
        countries_preferred='["Germany"]', confidence=0.9, active=True)
    session.add(row)
    session.flush()
    if frequency is not None:
        session.add(DigestPreference(
            profile_id=row.id, email=digest_email or "digest@example.com",
            frequency=frequency, include_matches=5, include_supervisors=False))
    session.commit()
    return row


def _seed_opportunity(session, *, title="PhD in radio astronomy",
                      country="Germany", score=0.99):
    opp = Opportunity(source="euraxess", source_raw=title, title=title,
                      institution="MPIfR", country=country,
                      short_description="Doctoral project on radio astronomy.",
                      url="https://ex.org/j/1", position_type="phd")
    session.add(opp)
    session.commit()
    return opp


def test_send_digest_job_sends_and_records(session, session_factory,
                                           monkeypatch):
    _seed_profile(session)
    _seed_opportunity(session)
    sent = {}

    def fake_send(to, subject, html, text=None, from_email=None):
        sent["to"] = to
        sent["subject"] = subject
        return {"status": "sent", "id": "resend_123"}

    monkeypatch.setattr(tasks.email, "send_email", fake_send)
    count = tasks.send_digest_job(1, session_factory=session_factory)
    assert count == 1
    assert sent["to"] == "digest@example.com"
    assert "astronomy/interstellar medium" in sent["subject"]

    event = session.query(EmailEvent).one()
    assert event.event_type == "sent"
    assert event.provider_id == "resend_123"
    assert event.email_to == "digest@example.com"


def test_send_digest_job_skips_when_frequency_never(session, session_factory,
                                                    monkeypatch):
    _seed_profile(session, frequency="never")
    _seed_opportunity(session)
    monkeypatch.setattr(tasks.email, "send_email",
                        lambda *a, **k: {"status": "sent", "id": "x"})
    count = tasks.send_digest_job(1, session_factory=session_factory)
    assert count == 0
    assert session.query(EmailEvent).count() == 0


def test_send_digest_job_skips_missing_profile(session, session_factory,
                                               monkeypatch):
    monkeypatch.setattr(tasks.email, "send_email",
                        lambda *a, **k: {"status": "sent", "id": "x"})
    count = tasks.send_digest_job(999, session_factory=session_factory)
    assert count == 0


def test_send_digest_job_never_raises_on_email_failure(session,
                                                       session_factory,
                                                       monkeypatch):
    _seed_profile(session)
    _seed_opportunity(session)
    monkeypatch.setattr(tasks.email, "send_email",
                        lambda *a, **k: {"status": "failed", "id": None})
    count = tasks.send_digest_job(1, session_factory=session_factory)
    assert count == 0
    assert session.query(EmailEvent).one().event_type == "failed"


def test_schedule_weekly_digests_enqueues_only_weekly(session, monkeypatch):
    _seed_profile(session, frequency="weekly", digest_email="a@example.com")
    _seed_profile(session, frequency="never", digest_email="b@example.com")
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_digest_job",
                        lambda pid: enqueued.append(pid) or "job-x")
    n = tasks._schedule_weekly_digests(session)
    assert n == 1
    assert len(enqueued) == 1


def test_schedule_weekly_digests_isolates_bad_profiles(session, monkeypatch):
    _seed_profile(session, frequency="weekly", digest_email="a@example.com")
    _seed_profile(session, frequency="weekly", digest_email="b@example.com")

    def flaky(pid):
        if pid == 2:
            raise RuntimeError("boom")
        return "job-x"

    monkeypatch.setattr(tasks, "enqueue_digest_job", flaky)
    n = tasks._schedule_weekly_digests(session)
    assert n == 1  # one failed enqueue is logged, not raised


def test_schedule_weekly_digests_idempotent_per_day(session, monkeypatch):
    """The batch claims the day BEFORE enqueueing, so a duplicate run (second
    worker, double cron, or a repeated fallback wakeup) enqueues nothing."""
    _seed_profile(session, frequency="weekly", digest_email="a@example.com")
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_digest_job",
                        lambda pid: enqueued.append(pid) or "job-x")
    assert tasks.schedule_weekly_digests(session=session) == 1
    assert tasks.schedule_weekly_digests(session=session) == 0
    assert len(enqueued) == 1


def test_schedule_weekly_digests_releases_claim_on_failure(session,
                                                           monkeypatch):
    """A catastrophic batch failure releases the day's claim so the next
    wakeup can retry instead of silently skipping until tomorrow."""
    _seed_profile(session, frequency="weekly", digest_email="a@example.com")
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_digest_job",
                        lambda pid: enqueued.append(pid) or "job-x")
    original = tasks._schedule_weekly_digests

    def boom(s):
        raise RuntimeError("batch died")

    monkeypatch.setattr(tasks, "_schedule_weekly_digests", boom)
    with pytest.raises(RuntimeError):
        tasks.schedule_weekly_digests(session=session)
    tasks._schedule_weekly_digests = original

    assert tasks.schedule_weekly_digests(session=session) == 1
    assert len(enqueued) == 1


def test_claim_digest_run_atomic_via_redis(monkeypatch):
    """Cross-worker idempotency: the Redis SET NX claim returns True once, then
    False for the rest of the day."""
    fake = _fake_redis()
    monkeypatch.setattr(tasks, "_redis", lambda: fake)
    assert tasks._claim_digest_run() is True
    assert tasks._claim_digest_run() is False


def _fake_redis():
    """Minimal fake exposing just the set(..., nx=True) API the claim uses."""
    class _SetNX:
        def __init__(self):
            self._keys = set()

        def set(self, key, value, ex=None, nx=False):
            if nx and key in self._keys:
                return None
            self._keys.add(key)
            return True

    return _SetNX()


def test_enqueue_digest_job_fallback_runs_synchronously(session, monkeypatch):
    _seed_profile(session)
    monkeypatch.setattr(tasks.email, "send_email",
                        lambda *a, **k: {"status": "sent", "id": "x"})
    # Force the in-process fallback path (no Redis) and stub the actual job so
    # it cannot touch the real default database file.
    monkeypatch.setattr(tasks, "_redis", lambda: None)
    monkeypatch.setattr(tasks, "send_digest_job", lambda pid, session_factory=None: 1)
    job_id = tasks.enqueue_digest_job(1)
    assert job_id
    # Fallback runs on a daemon thread; wait for completion.
    import time
    for _ in range(50):
        status = tasks.get_job_status(job_id)
        if status and status["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert tasks.get_job_status(job_id)["status"] == "completed"