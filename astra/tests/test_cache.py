"""tests.test_cache — Sprint 06, B1: the caching layer (core.cache).

Covers the in-memory fallback (no Redis configured in the test env) plus the
namespaced invalidation helpers and their interaction with the API routes
(match results cached + invalidated on profile change)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from core import cache
from db.models import Base, Opportunity

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset_memory_cache():
    from core import tasks
    tasks._in_memory_jobs.clear()
    cache.invalidate("")
    cache.invalidate_matches()
    cache.invalidate_opportunities()
    cache.invalidate_supervisors()
    yield
    tasks._in_memory_jobs.clear()
    cache.invalidate("")
    cache.invalidate_matches()
    cache.invalidate_opportunities()
    cache.invalidate_supervisors()


def test_in_memory_set_get_roundtrip():
    cache.set("k:1", {"a": [1, 2, 3]}, ttl=60)
    assert cache.get("k:1") == {"a": [1, 2, 3]}


def test_in_memory_missing_key_returns_none():
    assert cache.get("k:missing") is None


def test_in_memory_ttl_expiry(monkeypatch):
    import time as time_module
    real_monotonic = time_module.monotonic
    cache.set("k:ttl", "v", ttl=1)
    monkeypatch.setattr(time_module, "monotonic",
                        lambda: real_monotonic() + 10)
    assert cache.get("k:ttl") is None


def test_invalidate_prefix_removes_only_matching_keys():
    cache.set("matches:1", [1], ttl=60)
    cache.set("matches:2", [2], ttl=60)
    cache.set("opportunities:list", [3], ttl=60)
    n = cache.invalidate("matches:")
    assert n == 2
    assert cache.get("matches:1") is None
    assert cache.get("matches:2") is None
    assert cache.get("opportunities:list") == [3]


def test_match_helpers_roundtrip():
    cache.cache_match_results(7, [{"id": 1}, {"id": 2}])
    assert cache.get_cached_matches(7) == [{"id": 1}, {"id": 2}]
    cache.invalidate_matches(7)
    assert cache.get_cached_matches(7) is None


def test_opportunity_helpers_roundtrip():
    cache.cache_opportunity_list([{"id": 1}])
    assert cache.get_cached_opportunity_list() == [{"id": 1}]
    cache.invalidate_opportunities()
    assert cache.get_cached_opportunity_list() is None


def test_supervisor_helpers_roundtrip():
    cache.cache_supervisor_list([{"id": 1}])
    assert cache.get_cached_supervisor_list() == [{"id": 1}]
    cache.invalidate_supervisors()
    assert cache.get_cached_supervisor_list() is None


# ---------------------------------------------------------------------------
# Sprint 06 — B2: rq job queue (in-process fallback + mocked rq path)
# ---------------------------------------------------------------------------
def test_enqueue_fallback_runs_job(monkeypatch):
    from core import tasks

    def fake_run(country=None, sources=None, field=None,
                 on_progress=None, **_kw):
        return 3
    monkeypatch.setattr(tasks, "run_pipeline_job", fake_run)
    monkeypatch.setattr(tasks, "_redis", lambda: None)
    job_id = tasks.enqueue_pipeline_job(country="Germany")
    assert job_id
    deadline = time.time() + 5
    status = None
    while time.time() < deadline:
        status = tasks.get_job_status(job_id)
        if status and status["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert status["status"] == "completed"
    assert status["records"] == 3


def test_enqueue_rq_branch_uses_queue(monkeypatch):
    from core import tasks

    class _FakeJob:
        id = "fake-job-id"

    class _FakeQueue:
        def enqueue(self, fn, *args, **kwargs):
            return _FakeJob()

    class _FakeClient:
        pass

    monkeypatch.setattr(tasks, "_redis", lambda: _FakeClient())
    monkeypatch.setattr("rq.Queue", lambda connection: _FakeQueue())
    job_id = tasks.enqueue_pipeline_job(country="DE", sources=["eso"])
    assert job_id == "fake-job-id"


def test_cancel_running_job_fallback(monkeypatch):
    from core import tasks

    tasks._in_memory_jobs["c1"] = {"job_id": "c1", "status": "running"}
    monkeypatch.setattr(tasks, "_redis", lambda: None)
    assert tasks.cancel_job("c1") is True
    assert tasks.get_job_status("c1")["status"] == "cancelled"
    assert tasks.cancel_job("missing") is False


# ---------------------------------------------------------------------------
# API integration: matches cached, invalidated on profile build/update
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register",
                json={"email": "carol@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "carol@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_opportunity(session, **kw):
    opp = Opportunity(
        source=kw.get("source", "euraxess"),
        source_raw=kw.get("url", "https://ex.org/j"),
        title=kw.get("title", "PhD in radio astronomy"),
        country=kw.get("country", "Germany"),
        position_type=kw.get("position_type", "phd"),
        url=kw.get("url", "https://ex.org/j"),
        short_description=kw.get("short_description", "Doctoral project."),
    )
    session.add(opp)
    session.flush()
    return opp


def _mock_extract(monkeypatch, profile):
    monkeypatch.setattr("api.routes.profile.extract_profile",
                        lambda raw_text, llm: profile)


def test_matches_list_populates_cache(monkeypatch, db_session, client, auth):
    from core.profile_schema import UserProfile
    profile = UserProfile(
        domain="astronomy", subfield="interstellar medium",
        methods=["radio interferometry"], tools=["LOFAR"], skills=["dust"],
        experience_level="phd_student", target_roles=["postdoc"],
        countries_preferred=["Germany"], confidence=0.9, raw_text="CV.")
    _mock_extract(monkeypatch, profile)
    _seed_opportunity(db_session)
    db_session.commit()

    resp = client.post("/api/profile/build", headers=auth,
                       json={"raw_text": "CV."})
    assert resp.status_code == 201
    # Cache is populated lazily on first match listing; until then it is empty.
    assert cache.get_cached_matches(1) is None
    client.get("/api/matches", headers=auth)
    assert cache.get_cached_matches(1) is not None

    # Profile update invalidates the cached matches for that user.
    client.put("/api/profile", headers=auth, json={"domain": "physics"})
    assert cache.get_cached_matches(1) is None


def test_opportunities_unfiltered_served_from_cache(monkeypatch, db_session,
                                                    client, auth):
    from core.profile_schema import UserProfile
    profile = UserProfile(
        domain="astronomy", subfield="interstellar medium",
        methods=["radio interferometry"], tools=["LOFAR"], skills=["dust"],
        experience_level="phd_student", target_roles=["postdoc"],
        countries_preferred=["Germany"], confidence=0.9, raw_text="CV.")
    _mock_extract(monkeypatch, profile)
    _seed_opportunity(db_session)
    db_session.commit()

    client.post("/api/profile/build", headers=auth, json={"raw_text": "CV."})
    client.get("/api/opportunities")
    # The list is ranked by the active profile, so it is cached UNDER that
    # profile — a list cached for one set of keywords is wrong for another.
    from core.tasks import profile_terms
    fp = cache.profile_fingerprint(profile_terms(profile))
    assert fp != "none", "a real profile must produce a real fingerprint"
    assert cache.get_cached_opportunity_list(None, fp) is not None
    # Add another row; the cache (1h TTL) must not see it until invalidated.
    _seed_opportunity(db_session, url="https://ex.org/j/2",
                      title="PhD in cosmology")
    db_session.commit()
    cached = cache.get_cached_opportunity_list(None, fp)
    assert len(cached) == 1
    cache.invalidate_opportunities()
    client.get("/api/opportunities")
    assert len(cache.get_cached_opportunity_list(None, fp)) == 2
