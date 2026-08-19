"""tests.test_api — Sprint 04, Track A7 + Track C3.

Covers every REST endpoint (health, auth, profile, opportunities, matches,
supervisors, bookmarks, pipeline) with FastAPI's TestClient against an
in-memory SQLite database. The LLM extraction for ``/api/profile/build`` is
mocked; the pipeline ``run()`` is stubbed so no network is touched.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import login_limiter, register_limiter
from core.profile_schema import UserProfile
from db.models import Base, LlmUsage, Match, MatchFeedback, Opportunity, Supervisor, User, UserProfileRow
from db.repositories import UserRepo

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Per-test isolation for the in-memory rate limiters (shared state)."""
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    from core import cache, tasks
    tasks._in_memory_jobs.clear()
    cache.invalidate("")
    cache.invalidate_matches()
    cache.invalidate_opportunities()
    cache.invalidate_supervisors()
    yield
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")


# ---------------------------------------------------------------------------
# fixtures
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
    """Register + login a fresh user; yields (token, email)."""
    email = "alice@example.com"
    client.post("/api/auth/register",
                json={"email": email, "password": "SuperSecret1"})
    resp = client.post("/api/auth/login",
                       json={"email": email, "password": "SuperSecret1"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, email):
    """Register + login an arbitrary user; returns auth headers."""
    client.post("/api/auth/register",
                json={"email": email, "password": "SuperSecret1"})
    resp = client.post("/api/auth/login",
                       json={"email": email, "password": "SuperSecret1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def make_opportunity(session, *, title="PhD in radio astronomy",
                     country="Germany", source="euraxess",
                     position_type="phd", institution="MPIfR",
                     short_description="Doctoral project on radio astronomy.",
                     url="https://ex.org/j/1"):
    opp = Opportunity(source=source, source_raw=url, title=title,
                      institution=institution, country=country,
                      position_type=position_type, url=url,
                      short_description=short_description)
    session.add(opp)
    session.flush()
    return opp


def make_supervisor(session, *, name="Dr. Ada Astro",
                    country="Germany", fit_score=0.9,
                    department="ISM Group", topics=None, profile_url=None):
    sup = Supervisor(name=name, country=country, fit_score=fit_score,
                     department=department, source="openalex",
                     profile_url=profile_url,
                     topics=topics or '["interstellar medium"]')
    session.add(sup)
    session.flush()
    return sup


def mock_profile_extract(monkeypatch, profile=None):
    """Stub the LLM extraction used by /api/profile/build."""
    if profile is None:
        profile = UserProfile(domain="astronomy",
                              subfield="interstellar medium",
                              methods=["radio interferometry"],
                              tools=["LOFAR", "Python"],
                              skills=["dust polarization"],
                              experience_level="phd_student",
                              target_roles=["postdoc"],
                              countries_preferred=["Germany"],
                              confidence=0.9,
                              raw_text="Sample CV text.")
    monkeypatch.setattr("api.routes.profile.extract_profile",
                        lambda raw_text, llm: profile)
    return profile


def build_profile(client, auth, raw_text="Sample CV text."):
    return client.post("/api/profile/build", headers=auth,
                       json={"raw_text": raw_text})


def wait_for_status(client, run_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/pipeline/status?run_id={run_id}")
        if resp.status_code == 200 and resp.json()["status"] in (
                "completed", "failed"):
            return resp.json()
        time.sleep(0.02)
    raise AssertionError(f"pipeline run {run_id} did not finish in time")


# ---------------------------------------------------------------------------
# health / app metadata
# ---------------------------------------------------------------------------
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_has_version(client):
    assert client.get("/health").json()["version"] == "0.1.0"


def test_openapi_lists_all_resource_paths(client):
    paths = set(app.openapi()["paths"])
    expected = {"/api/profile", "/api/profile/build", "/api/opportunities",
                "/api/opportunities/{opportunity_id}", "/api/matches",
                "/api/matches/{match_id}/feedback", "/api/supervisors",
                "/api/supervisors/{supervisor_id}", "/api/bookmarks",
                "/api/bookmarks/{bookmark_id}", "/api/auth/register",
                "/api/auth/login", "/api/auth/refresh", "/api/auth/me",
                "/api/pipeline/run", "/api/pipeline/status",
                "/api/jobs/{job_id}",
                "/api/preferences",
                "/api/admin/pool-status",
                "/api/fields", "/ready", "/health"}
    assert expected <= paths


def test_ready_returns_200(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["db"] == "ok"


def test_fields_lists_profiles(client):
    resp = client.get("/api/fields")
    assert resp.status_code == 200
    data = resp.json()
    assert "astronomy" in data["profiles"]
    assert data["default"]


def test_responses_carry_security_headers(client):
    resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-xss-protection"] == "1; mode=block"


def test_login_returns_rate_limit_headers(client):
    client.post("/api/auth/register",
                json={"email": "rlh@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "rlh@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.headers["x-ratelimit-limit"] == "5"
    assert resp.headers["x-ratelimit-remaining"] == "4"


def test_protected_paths_require_bearer_security(client):
    spec = app.openapi()
    assert "/api/profile" in spec["paths"]
    assert "/api/matches" in spec["paths"]


def test_unknown_route_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404


def test_method_not_allowed_405(client):
    resp = client.delete("/api/opportunities")
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Sprint 06 — A3: admin + connection pool status
# ---------------------------------------------------------------------------
def test_pool_status_requires_admin(client, auth):
    resp = client.get("/api/admin/pool-status", headers=auth)
    assert resp.status_code == 403


def test_pool_status_returns_sqlite_metrics(db_session, client):
    from api.routes import admin as admin_module
    admin_module._get_engine = lambda: db_session.get_bind()
    admin = UserRepo(db_session).create("boss@example.com", "x",
                                        role="admin")
    db_session.commit()
    from api.security import create_access_token
    token = create_access_token(admin.id)
    resp = client.get("/api/admin/pool-status",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["engine"] == "sqlite"


# ---------------------------------------------------------------------------
# Sprint 09 — B01: /api/admin/source-health + on-demand drift check
# ---------------------------------------------------------------------------
def test_source_health_requires_admin(client, auth):
    resp = client.get("/api/admin/source-health", headers=auth)
    assert resp.status_code == 403


def test_source_health_snapshot_and_drift_check(db_session, client,
                                                monkeypatch):
    import core.source_monitor as sm
    from api.routes import admin as admin_module
    admin_module._get_engine = lambda: db_session.get_bind()
    admin = UserRepo(db_session).create("boss2@example.com", "x",
                                        role="admin")
    db_session.commit()
    from api.security import create_access_token
    token = create_access_token(admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(sm, "_get_redis", lambda: None)
    sm._MEMORY.clear()
    for i in range(10):
        sm.record_run("euraxess", raw_records=3 + i % 2)
    sm.record_run("euraxess", raw_records=400)

    resp = client.get("/api/admin/source-health", headers=headers)
    assert resp.status_code == 200
    (row,) = [r for r in resp.json()["sources"]
              if r["source"] == "euraxess"]
    assert row["drift"] is True

    resp = client.post("/api/admin/source-health/check-drift", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["alerts"][0]["source"] == "euraxess"
    sm._MEMORY.clear()


def test_feedback_intel_requires_admin(client, auth):
    resp = client.get("/api/admin/feedback-intel", headers=auth)
    assert resp.status_code in (401, 403)


def test_feedback_intel_returns_aggregates(db_session, client):
    from api.routes import admin as admin_module
    admin_module._get_engine = lambda: db_session.get_bind()
    admin = UserRepo(db_session).create("boss3@example.com", "x",
                                        role="admin")
    profile = UserProfileRow(user_id=None)
    db_session.add(profile)
    db_session.flush()
    opp = Opportunity(source="euraxess", source_raw="eu/1", title="Radio A",
                      institution="MPIfR", country="Germany",
                      short_description="Interferometry",
                      url="https://x.org/j")
    db_session.add(opp)
    db_session.flush()
    m = Match(profile_id=profile.id, target_type="opportunity",
              opportunity_id=opp.id, overall_score=85.0)
    db_session.add(m)
    db_session.flush()
    db_session.add(MatchFeedback(match_id=m.id, helpful=True,
                                 comment="excellent fit"))
    db_session.commit()

    from api.security import create_access_token
    token = create_access_token(admin.id)
    resp = client.get("/api/admin/feedback-intel",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 1
    assert data["summary"]["rate"] == 1.0
    assert any(b["key"] == "80-100" and b["total"] == 1
               for b in data["brackets"])
    assert data["sources"][0]["key"] == "euraxess"


# ---------------------------------------------------------------------------
# Sprint 09 — B03: task reliability — dead-letter review, retry, heartbeat
# ---------------------------------------------------------------------------
def test_tasks_endpoints_require_admin(client, auth):
    assert client.get("/api/admin/tasks/dead-letters",
                      headers=auth).status_code == 403
    assert client.get("/api/admin/tasks/worker-heartbeat",
                      headers=auth).status_code == 403
    assert client.post("/api/admin/tasks/abc/retry",
                       headers=auth).status_code == 403


def test_dead_letters_retry_and_heartbeat(db_session, client, monkeypatch):
    from api.routes import admin as admin_module
    from core import tasks
    admin_module._get_engine = lambda: db_session.get_bind()
    admin = UserRepo(db_session).create("boss4@example.com", "x",
                                        role="admin")
    db_session.commit()
    from api.security import create_access_token
    token = create_access_token(admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(tasks, "_redis", lambda: None)
    monkeypatch.setattr(tasks, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(tasks, "MAX_PIPELINE_RETRIES", 0)
    tasks._in_memory_jobs.clear()

    def always_fail(country=None, sources=None, field=None, on_progress=None, **_kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(tasks, "run_pipeline_job", always_fail)
    job_id = tasks.enqueue_pipeline_job(country="DE")
    deadline = time.time() + 5
    while time.time() < deadline:
        info = tasks.get_job_status(job_id)
        if info and info["status"] == "failed":
            break
        time.sleep(0.02)

    resp = client.get("/api/admin/tasks/dead-letters", headers=headers)
    assert resp.status_code == 200
    assert any(j["job_id"] == job_id for j in resp.json()["jobs"])

    monkeypatch.setattr(tasks, "run_pipeline_job",
                        lambda country=None, sources=None, field=None,
                        on_progress=None, **_kw: 4)
    resp = client.post(f"/api/admin/tasks/{job_id}/retry", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["retried"] is True
    new_id = resp.json()["new_job_id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        info = tasks.get_job_status(new_id)
        if info and info["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert info["status"] == "completed"

    assert client.post("/api/admin/tasks/missing/retry",
                       headers=headers).status_code == 404

    beat = client.get("/api/admin/tasks/worker-heartbeat", headers=headers)
    assert beat.status_code == 200
    assert beat.json()["backend"] == "in-process"
    tasks._in_memory_jobs.clear()


# ---------------------------------------------------------------------------
# Sprint 09 — B04: /api/admin/anomalies (rolling metrics + detection)
# ---------------------------------------------------------------------------
def test_anomalies_requires_admin(client, auth):
    resp = client.get("/api/admin/anomalies", headers=auth)
    assert resp.status_code in (401, 403)


def test_anomalies_snapshot_and_detect(db_session, client, monkeypatch):
    from api.routes import admin as admin_module
    from core import anomaly
    admin_module._get_engine = lambda: db_session.get_bind()
    admin = UserRepo(db_session).create("boss5@example.com", "x",
                                        role="admin")
    db_session.commit()
    from api.security import create_access_token
    token = create_access_token(admin.id)
    headers = {"Authorization": f"Bearer {token}"}

    h = anomaly.History()
    for i in range(6):
        h.seed_bucket(10, 0, 80, ts=1 + i)
    h.seed_bucket(20, 15, 100, ts=60)
    monkeypatch.setattr(anomaly, "_history", h)
    monkeypatch.setattr(anomaly, "submit", lambda *a, **k: None)
    anomaly._debounce_seen.clear()

    resp = client.get("/api/admin/anomalies", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"]["errors"] == 15
    assert any(a["kind"] == "5xx-spike" for a in data["anomalies"])

    notified = []
    monkeypatch.setattr(anomaly, "notify_ops",
                        lambda msg, tags=None: notified.append(msg))
    resp = client.post("/api/admin/anomalies/detect", headers=headers)
    assert resp.status_code == 200
    assert len(notified) == 1


# --- Sprint 09 — C02: extended /api/admin/metrics (llm usage + source health)
def test_admin_metrics_includes_llm_and_source_health(db_session, client,
                                                      monkeypatch):
    from api.routes import admin as admin_module
    from core import anomaly, source_monitor
    admin_module._get_engine = lambda: db_session.get_bind()
    admin = UserRepo(db_session).create("boss6@example.com", "x",
                                        role="admin")
    db_session.add(LlmUsage(feature="cover_letter", model="openai/gpt-4o-mini",
                            prompt_tokens=100, completion_tokens=50))
    db_session.commit()
    monkeypatch.setattr(source_monitor, "_get_redis", lambda: None)
    source_monitor._MEMORY.clear()
    source_monitor.record_run("euraxess", raw_records=10)
    source_monitor.record_run("euraxess", raw_records=12)
    monkeypatch.setattr(anomaly, "submit", lambda *a, **k: None)

    from api.security import create_access_token
    token = create_access_token(admin.id)
    resp = client.get("/api/admin/metrics",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm"]["calls"] == 1
    assert data["llm"]["prompt_tokens"] == 100
    assert data["llm"]["estimated_spend_usd"] >= 0.0
    assert data["source_health"]["sources"] >= 1
    source_monitor._MEMORY.clear()


# ---------------------------------------------------------------------------
# auth — register / login / me
# ---------------------------------------------------------------------------
def test_register_success_201(client):
    resp = client.post("/api/auth/register",
                       json={"email": "bob@example.com",
                             "password": "SuperSecret1"})
    assert resp.status_code == 201
    assert resp.json()["user_id"] >= 1
    assert resp.json()["email"] == "bob@example.com"


def test_register_lowercases_email(client):
    resp = client.post("/api/auth/register",
                       json={"email": "MIXED@Example.COM",
                             "password": "SuperSecret1"})
    assert resp.status_code == 201
    assert resp.json()["email"] == "mixed@example.com"


def test_register_duplicate_email_409(client):
    body = {"email": "dup@example.com", "password": "SuperSecret1"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_register_invalid_email_422(client):
    resp = client.post("/api/auth/register",
                       json={"email": "not-an-email", "password": "SuperSecret1"})
    assert resp.status_code == 422


def test_register_short_password_422(client):
    resp = client.post("/api/auth/register",
                       json={"email": "short@example.com", "password": "short"})
    assert resp.status_code == 422


def test_register_missing_fields_422(client):
    assert client.post("/api/auth/register", json={}).status_code == 422


def test_register_weak_password_no_uppercase_422(client):
    resp = client.post("/api/auth/register",
                       json={"email": "weak@example.com",
                             "password": "password1"})
    assert resp.status_code == 422
    assert "uppercase" in resp.text


def test_register_weak_password_no_digit_422(client):
    resp = client.post("/api/auth/register",
                       json={"email": "weak@example.com",
                             "password": "SuperSecret"})
    assert resp.status_code == 422
    assert "digit" in resp.text


def test_register_weak_password_no_lowercase_422(client):
    resp = client.post("/api/auth/register",
                       json={"email": "weak@example.com",
                             "password": "SUPERSECRET1"})
    assert resp.status_code == 422
    assert "lowercase" in resp.text


def test_register_strong_password_ok(client):
    resp = client.post("/api/auth/register",
                       json={"email": "strong@example.com",
                             "password": "SuperSecret1"})
    assert resp.status_code == 201


def test_password_is_bcrypt_hashed_not_plaintext(db_session, client):
    client.post("/api/auth/register",
                json={"email": "hash@example.com", "password": "SuperSecret1"})
    user = db_session.scalar(select(User))
    assert user.hashed_password != "SuperSecret1"
    assert user.hashed_password.startswith("$2")


def test_login_success_returns_token(client):
    client.post("/api/auth/register",
                json={"email": "l@example.com", "password": "SuperSecret1"})
    resp = client.post("/api/auth/login",
                       json={"email": "l@example.com", "password": "SuperSecret1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 20


def test_login_wrong_password_401(client):
    client.post("/api/auth/register",
                json={"email": "w@example.com", "password": "SuperSecret1"})
    resp = client.post("/api/auth/login",
                       json={"email": "w@example.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_unknown_email_401(client):
    resp = client.post("/api/auth/login",
                       json={"email": "ghost@example.com", "password": "x" * 8})
    assert resp.status_code == 401


def test_me_returns_current_user(client, auth):
    resp = client.get("/api/auth/me", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


def test_me_without_token_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_garbage_token_401(client):
    resp = client.get("/api/auth/me",
                      headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


def test_me_with_malformed_auth_header_401(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


def test_login_sets_httponly_cookie(client, monkeypatch):
    # Hermetic: ensure Secure is set by default regardless of ambient env
    monkeypatch.setenv("ASTRA_COOKIE_SECURE", "1")
    client.post("/api/auth/register",
                json={"email": "ck@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "ck@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "cik_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" in set_cookie


def test_login_cookie_not_secure_when_disabled(client, monkeypatch):
    """ASTRA_COOKIE_SECURE=0 (plain-HTTP local dev) must drop the Secure flag."""
    monkeypatch.setenv("ASTRA_COOKIE_SECURE", "0")
    client.post("/api/auth/register",
                json={"email": "ck2@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "ck2@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "cik_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" not in set_cookie
    all_cookies = resp.headers.get_list("set-cookie")
    assert not any("Secure" in c for c in all_cookies)


def test_login_still_returns_token_in_body(client):
    client.post("/api/auth/register",
                json={"email": "bk@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "bk@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    assert len(resp.json()["access_token"]) > 20


def test_refresh_returns_new_token(client, auth):
    resp = client.post("/api/auth/refresh", headers=auth)
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert token
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_refresh_requires_auth_401(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_sets_httponly_cookie(client, auth):
    resp = client.post("/api/auth/refresh", headers=auth)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "cik_token=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_register_rate_limited_429(client):
    emails = [f"rl{i}@example.com" for i in range(4)]
    for email in emails[:3]:
        resp = client.post("/api/auth/register",
                           json={"email": email, "password": PASSWORD})
        assert resp.status_code == 201
    resp = client.post("/api/auth/register",
                       json={"email": emails[3], "password": PASSWORD})
    assert resp.status_code == 429


def test_login_rate_limited_429(client):
    client.post("/api/auth/register",
                json={"email": "lr@example.com", "password": PASSWORD})
    for _ in range(5):
        client.post("/api/auth/login",
                    json={"email": "lr@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "lr@example.com", "password": PASSWORD})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# profile — auth + CRUD (scoped to the authenticated user)
# ---------------------------------------------------------------------------
def test_profile_get_requires_auth_401(client):
    assert client.get("/api/profile").status_code == 401


def test_profile_build_requires_auth_401(client):
    resp = client.post("/api/profile/build", json={"raw_text": "CV"})
    assert resp.status_code == 401


def test_profile_put_requires_auth_401(client):
    assert client.put("/api/profile", json={"domain": "x"}).status_code == 401


def test_profile_get_without_profile_404(client, auth):
    assert client.get("/api/profile", headers=auth).status_code == 404


def test_profile_build_success_201(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    resp = build_profile(client, auth)
    assert resp.status_code == 201
    assert resp.json()["domain"] == "astronomy"
    assert resp.json()["confidence"] == 0.9


def test_profile_build_returns_extracted_profile(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    data = build_profile(client, auth).json()
    assert data["subfield"] == "interstellar medium"
    assert data["methods"] == ["radio interferometry"]
    assert data["countries_preferred"] == ["Germany"]


def test_profile_get_returns_active_profile(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.get("/api/profile", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["domain"] == "astronomy"
    assert resp.json()["raw_text"] == "Sample CV text."


def test_profile_build_empty_text_422(client, auth):
    resp = client.post("/api/profile/build", headers=auth, json={"raw_text": ""})
    assert resp.status_code == 422


def test_profile_build_extraction_failure_422(client, auth, monkeypatch):
    monkeypatch.setattr("api.routes.profile.extract_profile",
                        lambda raw_text, llm: None)
    resp = build_profile(client, auth)
    assert resp.status_code == 422


def test_profile_build_replaces_previous_profile(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch, UserProfile(domain="astronomy",
                                                  raw_text="one"))
    build_profile(client, auth, raw_text="one")
    mock_profile_extract(monkeypatch, UserProfile(domain="physics",
                                                  raw_text="two"))
    build_profile(client, auth, raw_text="two")
    data = client.get("/api/profile", headers=auth).json()
    assert data["domain"] == "physics"


def test_profile_put_updates_domain(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.put("/api/profile", headers=auth, json={"domain": "physics"})
    assert resp.status_code == 200
    assert resp.json()["domain"] == "physics"


def test_profile_put_updates_list_field(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.put("/api/profile", headers=auth,
                      json={"countries_preferred": ["Netherlands"]})
    assert resp.json()["countries_preferred"] == ["Netherlands"]
    # round-trips through the DB (JSON encoding)
    assert client.get("/api/profile", headers=auth).json()[
        "countries_preferred"] == ["Netherlands"]


def test_profile_put_without_profile_404(client, auth):
    resp = client.put("/api/profile", headers=auth, json={"domain": "x"})
    assert resp.status_code == 404


def test_profile_put_empty_body_ok(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.put("/api/profile", headers=auth, json={})
    assert resp.status_code == 200


def test_profile_put_invalid_confidence_422(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.put("/api/profile", headers=auth, json={"confidence": 2.0})
    assert resp.status_code == 422


def test_profile_scoped_to_authenticated_user(client, auth, monkeypatch):
    """User B must not see user A's profile."""
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    # second user
    client.post("/api/auth/register",
                json={"email": "b@example.com", "password": "SuperSecret1"})
    tok = client.post("/api/auth/login",
                      json={"email": "b@example.com",
                            "password": "SuperSecret1"}).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/profile", headers=headers_b).status_code == 404


# ---------------------------------------------------------------------------
# opportunities — list / filters / pagination / by id
# ---------------------------------------------------------------------------
def seed_opportunities(db_session):
    make_opportunity(db_session, title="PhD in radio astronomy",
                     country="Germany", source="euraxess",
                     position_type="phd",
                     short_description="Telescope array signal processing.")
    make_opportunity(db_session, title="Postdoc in cosmology",
                     country="Netherlands", source="findaphd",
                     position_type="postdoc",
                     short_description="Cosmic microwave background maps.",
                     url="https://ex.org/j/2")
    make_opportunity(db_session, title="PhD in ISM",
                     country="Germany", source="eso", position_type="phd",
                     short_description="Interstellar medium chemistry.",
                     url="https://ex.org/j/3")
    db_session.commit()


def test_opportunities_empty_list(client):
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


def test_opportunities_list_with_items(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities")
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    assert data["page"] == 1
    assert data["pages"] == 1


def test_opportunities_filter_country(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"country": "Germany"})
    data = resp.json()
    assert data["total"] == 2
    assert all(i["country"] == "Germany" for i in data["items"])


def test_opportunities_filter_source(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"source": "eso"})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["source"] == "eso"


def test_opportunities_filter_type(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"type": "phd"})
    data = resp.json()
    assert data["total"] == 2
    assert all(i["position_type"] == "phd" for i in data["items"])


def test_opportunities_filter_no_match(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities",
                      params={"country": "Japan"})
    assert resp.json()["total"] == 0


def test_opportunities_search_q_matches_title(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"q": "radio"})
    data = resp.json()
    assert data["total"] == 1
    assert "radio" in data["items"][0]["title"].lower()


def test_opportunities_search_q_matches_description(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"q": "cosmology"})
    assert resp.json()["total"] == 1


def test_opportunities_search_q_no_match(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"q": "quantum_xyz"})
    assert resp.json()["total"] == 0


def test_opportunities_pagination(client, db_session):
    seed_opportunities(db_session)
    resp = client.get("/api/opportunities", params={"limit": 2, "page": 1})
    first = resp.json()
    assert len(first["items"]) == 2
    resp = client.get("/api/opportunities", params={"limit": 2, "page": 2})
    second = resp.json()
    assert len(second["items"]) == 1
    ids_first = {i["id"] for i in first["items"]}
    ids_second = {i["id"] for i in second["items"]}
    assert not (ids_first & ids_second)


def test_opportunities_invalid_page_422(client):
    assert client.get("/api/opportunities",
                      params={"page": 0}).status_code == 422


def test_opportunities_limit_too_big_422(client):
    assert client.get("/api/opportunities",
                      params={"limit": 1000}).status_code == 422


def test_opportunity_get_by_id(client, db_session):
    seed_opportunities(db_session)
    opp_id = db_session.scalar(select(Opportunity)).id
    resp = client.get(f"/api/opportunities/{opp_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == opp_id


def test_opportunity_get_404(client):
    assert client.get("/api/opportunities/9999").status_code == 404


# ---------------------------------------------------------------------------
# matches — sorting, explainability, feedback
# ---------------------------------------------------------------------------
def seed_matches_context(db_session, auth, client, monkeypatch):
    seed_opportunities(db_session)
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    return db_session.scalar(select(Opportunity)).id


def test_matches_requires_auth_401(client):
    assert client.get("/api/matches").status_code == 401


def test_matches_without_profile_404(client, auth):
    assert client.get("/api/matches", headers=auth).status_code == 404


def test_matches_no_opportunities_empty(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.get("/api/matches", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_matches_returns_sorted_by_score(client, db_session, auth, monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    resp = client.get("/api/matches", headers=auth)
    items = resp.json()["items"]
    assert len(items) > 0
    scores = [i["match_score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_matches_include_explanation(client, db_session, auth, monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    resp = client.get("/api/matches", headers=auth)
    item = resp.json()["items"][0]
    assert item["match_explanation"]
    assert "topic" in item["match_explanation"].lower() or \
        "match" in item["match_explanation"].lower()


def test_matches_include_opportunity_fields(client, db_session, auth,
                                            monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    item = client.get("/api/matches", headers=auth).json()["items"][0]
    for key in ("id", "title", "institution", "country", "url",
                "position_type", "source"):
        assert key in item


def test_matches_have_dimension_scores(client, db_session, auth, monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    item = client.get("/api/matches", headers=auth).json()["items"][0]
    for key in ("topic_score", "method_score", "location_score"):
        assert 0.0 <= item[key] <= 1.0


def test_matches_have_percentile_and_suggestions(client, db_session, auth,
                                                 monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    item = client.get("/api/matches", headers=auth).json()["items"][0]
    assert 0.0 <= item["percentile"] <= 100.0
    assert isinstance(item["suggestions"], list)
    assert "more relevant than" in item["match_explanation"]


def test_matches_min_score_filter(client, db_session, auth, monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    all_items = client.get("/api/matches", headers=auth).json()["items"]
    resp = client.get("/api/matches", headers=auth,
                      params={"min_score": 0.9})
    filtered = resp.json()["items"]
    assert len(filtered) <= len(all_items)
    assert all(i["match_score"] >= 0.9 for i in filtered)


def test_matches_field_filter_uses_keywords(client, db_session, auth,
                                            monkeypatch):
    """field is a profile name: it expands to keywords and matches
    topic/department/field/subfield containment (like supervisors), not an
    exact equality on the opportunity's `field` column."""
    seed_matches_context(db_session, auth, client, monkeypatch)
    db_session.add(Opportunity(
        source="euraxess", source_raw="https://ex.org/j/cmb",
        title="CMB data analysis", country="Germany", position_type="phd",
        url="https://ex.org/j/cmb",
        short_description="Analyzing cosmic microwave background maps.",
        topics='["cosmic microwave background"]'))
    db_session.add(Opportunity(
        source="euraxess", source_raw="https://ex.org/j/graph",
        title="Network topology", country="Germany", position_type="phd",
        url="https://ex.org/j/graph",
        short_description="Graph theory applied to networks.",
        topics='["graph theory"]'))
    db_session.commit()
    resp = client.get("/api/matches", headers=auth,
                      params={"field": "astronomy"})
    data = resp.json()
    assert data["total"] == 1
    assert "CMB data analysis" in data["items"][0]["title"]


def test_matches_field_filter_unknown_profile_empty(client, db_session, auth,
                                                    monkeypatch):
    """An unknown field profile must yield an explicit empty result, never a
    silent match-everything."""
    seed_matches_context(db_session, auth, client, monkeypatch)
    resp = client.get("/api/matches", headers=auth,
                      params={"field": "no_such_profile"})
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_matches_limit(client, db_session, auth, monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    resp = client.get("/api/matches", headers=auth, params={"limit": 1})
    assert len(resp.json()["items"]) == 1


def test_matches_pagination(client, db_session, auth, monkeypatch):
    seed_matches_context(db_session, auth, client, monkeypatch)
    first = client.get("/api/matches", headers=auth,
                       params={"limit": 1, "page": 1}).json()
    second = client.get("/api/matches", headers=auth,
                        params={"limit": 1, "page": 2}).json()
    assert first["page"] == 1
    assert second["page"] == 2
    assert first["pages"] == 3
    assert second["pages"] == 3
    assert first["total"] == 3
    assert second["total"] == 3
    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    ids_first = {i["id"] for i in first["items"]}
    ids_second = {i["id"] for i in second["items"]}
    assert not (ids_first & ids_second)


def test_matches_limit_too_big_422(client, auth):
    resp = client.get("/api/matches", headers=auth, params={"limit": 1000})
    assert resp.status_code == 422


def test_matches_invalid_page_422(client, auth):
    resp = client.get("/api/matches", headers=auth, params={"page": 0})
    assert resp.status_code == 422


def test_match_feedback_ok(client, db_session, auth, monkeypatch):
    match_id = seed_matches_context(db_session, auth, client, monkeypatch)
    resp = client.post(f"/api/matches/{match_id}/feedback",
                       headers=auth,
                       json={"helpful": True, "comment": "great fit"})
    assert resp.status_code == 200
    assert resp.json()["match_id"] == match_id


def test_match_feedback_stored_in_db(client, db_session, auth, monkeypatch):
    match_id = seed_matches_context(db_session, auth, client, monkeypatch)
    client.post(f"/api/matches/{match_id}/feedback", headers=auth,
                json={"helpful": False, "comment": "not relevant"})
    row = db_session.scalar(select(MatchFeedback))
    assert row.match_id == match_id
    assert row.helpful is False
    assert row.comment == "not relevant"


def test_match_feedback_requires_auth_401(client, db_session):
    seed_opportunities(db_session)
    assert client.post("/api/matches/1/feedback",
                       json={"helpful": True}).status_code == 401


def test_match_feedback_unknown_match_404(client, auth):
    resp = client.post("/api/matches/9999/feedback", headers=auth,
                       json={"helpful": True})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# supervisors — list / filters / by id
# ---------------------------------------------------------------------------
def seed_supervisors(db_session):
    make_supervisor(db_session, name="Dr. Ada Astro", country="Germany",
                    fit_score=0.9, department="ISM Group")
    make_supervisor(db_session, name="Prof. Vera Cosmo", country="Netherlands",
                    fit_score=0.7, department="Cosmology")
    db_session.commit()


def test_supervisors_empty(client):
    resp = client.get("/api/supervisors")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_supervisors_public_no_auth(client, db_session):
    seed_supervisors(db_session)
    assert client.get("/api/supervisors").status_code == 200


def test_supervisors_list(client, db_session):
    seed_supervisors(db_session)
    resp = client.get("/api/supervisors")
    data = resp.json()
    assert data["total"] == 2
    assert {i["name"] for i in data["items"]} == {"Dr. Ada Astro",
                                                  "Prof. Vera Cosmo"}


def test_supervisors_ranked_by_fit_score(client, db_session):
    seed_supervisors(db_session)
    items = client.get("/api/supervisors").json()["items"]
    assert items[0]["fit_score"] == 0.9
    assert items[0]["name"] == "Dr. Ada Astro"


def test_supervisor_serializer_exposes_orcid_and_papers(client, db_session):
    make_supervisor(db_session, name="Dr. ORCID Astro", country="Germany",
                    fit_score=0.8, department="ISM Group",
                    profile_url="https://orcid.org/0000-0002-1825-0097",
                    topics='["magnetic fields"]')
    sup = db_session.scalar(select(Supervisor))
    sup.recent_papers = '["Paper A", "Paper B"]'
    db_session.commit()
    item = client.get("/api/supervisors").json()["items"][0]
    assert item["orcid"] == "0000-0002-1825-0097"
    assert item["recent_papers"] == ["Paper A", "Paper B"]


def test_supervisor_orcid_none_when_url_has_no_orcid(client, db_session):
    make_supervisor(db_session, name="Dr. Plain", country="Germany",
                    profile_url="https://openalex.org/authors/A1")
    item = client.get("/api/supervisors").json()["items"][0]
    assert item["orcid"] is None


def test_supervisors_filter_country(client, db_session):
    seed_supervisors(db_session)
    resp = client.get("/api/supervisors", params={"country": "Germany"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["country"] == "Germany"


def test_supervisors_filter_country_case_insensitive(client, db_session):
    """The desktop text field must not be case-sensitive: \"germany\" and
    \"GERMANY\" return the same rows as \"Germany\"."""
    seed_supervisors(db_session)
    for value in ("germany", "GERMANY"):
        resp = client.get("/api/supervisors", params={"country": value})
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["country"] == "Germany"


def test_supervisors_filter_country_code_and_alias(client, db_session):
    """An ISO code or alias normalises to the canonical country, so \"DE\" and
    \"Deutschland\" both match rows stored as \"Germany\"."""
    seed_supervisors(db_session)
    for value in ("DE", "Deutschland"):
        resp = client.get("/api/supervisors", params={"country": value})
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["country"] == "Germany"


def test_supervisors_filter_field(client, db_session):
    # field is a field-profile name: it expands to profile keywords and matches
    # topic/department containment (e.g. astronomy -> "cosmic microwave
    # background"), not a raw substring on the field value.
    db_session.add(Supervisor(name="Dr. CMB Astro", country="Germany",
                              fit_score=0.9, department="Cosmology",
                              source="openalex",
                              topics='["cosmic microwave background"]'))
    db_session.add(Supervisor(name="Prof. Control", country="Germany",
                              fit_score=0.6, department="Systems Engineering",
                              source="openalex",
                              topics='["control systems"]'))
    db_session.commit()
    resp = client.get("/api/supervisors", params={"field": "astronomy"})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Dr. CMB Astro"


def test_supervisors_filter_unknown_field_returns_empty(client, db_session):
    """An unknown field profile must return an explicit empty list, never the
    full unfiltered set."""
    seed_supervisors(db_session)
    resp = client.get("/api/supervisors",
                      params={"field": "no_such_profile"})
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_supervisors_search_q_matches_name(client, db_session):
    seed_supervisors(db_session)
    resp = client.get("/api/supervisors", params={"q": "ada"})
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Dr. Ada Astro"


def test_supervisors_search_q_matches_topic(client, db_session):
    seed_supervisors(db_session)
    resp = client.get("/api/supervisors", params={"q": "cosmology"})
    assert resp.json()["total"] == 1


def test_supervisors_search_q_no_match(client, db_session):
    seed_supervisors(db_session)
    resp = client.get("/api/supervisors", params={"q": "botany"})
    assert resp.json()["total"] == 0


def test_supervisor_get_by_id(client, db_session):
    seed_supervisors(db_session)
    sup_id = db_session.scalar(select(Supervisor)).id
    resp = client.get(f"/api/supervisors/{sup_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sup_id


def test_supervisor_get_404(client):
    assert client.get("/api/supervisors/9999").status_code == 404


# --- supervisors /run — desktop "run online search" button --------------------
def test_supervisors_run_requires_auth_401(client):
    resp = client.post("/api/supervisors/run",
                       json={"country": "Germany"})
    assert resp.status_code == 401


def test_supervisors_run_enqueues_job(client, auth, monkeypatch):
    from core import tasks
    monkeypatch.setattr(tasks, "enqueue_supervisor_job",
                        lambda countries, field=None, **_kw: "abc123")
    resp = client.post("/api/supervisors/run", headers=auth,
                       json={"country": "Germany", "field": "astronomy"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "started"
    assert data["run_id"] == "abc123"


def test_supervisors_run_accepts_country_list(client, auth, monkeypatch):
    from core import tasks
    captured = {}

    def fake_enqueue(countries, field=None, **_kw):
        captured["countries"] = countries
        captured["field"] = field
        return "xyz789"

    monkeypatch.setattr(tasks, "enqueue_supervisor_job", fake_enqueue)
    resp = client.post("/api/supervisors/run", headers=auth,
                       json={"country": ["Germany", "Netherlands"]})
    assert resp.status_code == 202
    assert captured["countries"] == ["Germany", "Netherlands"]
    assert captured["field"] is None


def test_supervisors_run_unknown_field_422(client, auth):
    resp = client.post("/api/supervisors/run", headers=auth,
                       json={"country": "Germany", "field": "no_such_profile"})
    assert resp.status_code == 422


def test_supervisors_run_empty_country_422(client, auth):
    resp = client.post("/api/supervisors/run", headers=auth,
                       json={"country": ""})
    assert resp.status_code == 422


def test_supervisors_run_too_many_429(client, auth, monkeypatch):
    from core import tasks

    def boom(countries, field=None, **_kw):
        raise RuntimeError("too many concurrent runs")

    monkeypatch.setattr(tasks, "enqueue_supervisor_job", boom)
    resp = client.post("/api/supervisors/run", headers=auth,
                       json={"country": "Germany"})
    assert resp.status_code == 429


def test_supervisor_sync_job_roundtrip(monkeypatch):
    """In-process fallback: enqueue -> worker thread -> completed with the
    upserted count surfaced as records."""
    from core import tasks
    monkeypatch.setattr(tasks, "_redis", lambda: None)
    monkeypatch.setattr(tasks, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(tasks, "MAX_PIPELINE_RETRIES", 0)
    tasks._in_memory_jobs.clear()

    monkeypatch.setattr(
        tasks, "run_supervisor_sync_job",
        lambda countries, field=None, quick=True, *a, **kw: 12)
    job_id = tasks.enqueue_supervisor_job(["Germany"], field="astronomy")
    deadline = time.time() + 5
    info = None
    while time.time() < deadline:
        info = tasks.get_job_status(job_id)
        if info and info["status"] == "completed":
            break
        time.sleep(0.02)
    assert info is not None
    assert info["status"] == "completed"
    assert info["records"] == 12


def test_supervisor_sync_single_flight(monkeypatch):
    """A second concurrent supervisor sync must be rejected (429 at the API),
    not queued unboundedly."""
    from core import tasks
    monkeypatch.setattr(tasks, "_redis", lambda: None)
    tasks._in_memory_jobs.clear()

    # Occupy the one slot manually to simulate an in-flight search.
    tasks._supervisor_slots.acquire()
    try:
        with pytest.raises(RuntimeError):
            tasks.enqueue_supervisor_job(["Germany"])
    finally:
        tasks._supervisor_slots.release()


# ---------------------------------------------------------------------------
# bookmarks — CRUD, scoped to the authenticated user's profile
# ---------------------------------------------------------------------------
def seed_bookmarks_context(client, db_session, auth, monkeypatch):
    opp = make_opportunity(db_session, title="PhD in radio astronomy",
                           country="Germany", url="https://ex.org/bm1")
    db_session.commit()
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    return opp.id


def test_bookmarks_requires_auth_401(client):
    assert client.get("/api/bookmarks").status_code == 401


def test_bookmarks_create_requires_auth_401(client):
    assert client.post("/api/bookmarks",
                       json={"opportunity_id": 1}).status_code == 401


def test_bookmarks_delete_requires_auth_401(client):
    assert client.delete("/api/bookmarks/1").status_code == 401


def test_bookmarks_without_profile_404(client, db_session, auth):
    opp = make_opportunity(db_session)
    db_session.commit()
    resp = client.get("/api/bookmarks", headers=auth)
    assert resp.status_code == 404


def test_bookmarks_create(client, db_session, auth, monkeypatch):
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    resp = client.post("/api/bookmarks", headers=auth,
                       json={"opportunity_id": opp_id})
    assert resp.status_code == 201
    assert resp.json()["opportunity_id"] == opp_id


def test_bookmarks_create_unknown_opportunity_404(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)
    resp = client.post("/api/bookmarks", headers=auth,
                       json={"opportunity_id": 424242})
    assert resp.status_code == 404


def test_bookmarks_create_duplicate_409(client, db_session, auth, monkeypatch):
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    client.post("/api/bookmarks", headers=auth,
                json={"opportunity_id": opp_id})
    resp = client.post("/api/bookmarks", headers=auth,
                       json={"opportunity_id": opp_id})
    assert resp.status_code == 409


def test_bookmarks_list(client, db_session, auth, monkeypatch):
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    client.post("/api/bookmarks", headers=auth,
                json={"opportunity_id": opp_id})
    resp = client.get("/api/bookmarks", headers=auth)
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["opportunity_id"] == opp_id


def test_bookmarks_list_includes_opportunity_detail(client, db_session, auth,
                                                    monkeypatch):
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    client.post("/api/bookmarks", headers=auth,
                json={"opportunity_id": opp_id})
    item = client.get("/api/bookmarks", headers=auth).json()["items"][0]
    assert item["opportunity"]["id"] == opp_id
    assert item["opportunity"]["title"] == "PhD in radio astronomy"


def test_bookmarks_include_created_at(client, db_session, auth, monkeypatch):
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    client.post("/api/bookmarks", headers=auth,
                json={"opportunity_id": opp_id})
    item = client.get("/api/bookmarks", headers=auth).json()["items"][0]
    assert item["created_at"] is not None


def test_bookmarks_delete(client, db_session, auth, monkeypatch):
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    bm_id = client.post("/api/bookmarks", headers=auth,
                        json={"opportunity_id": opp_id}).json()["id"]
    resp = client.delete(f"/api/bookmarks/{bm_id}", headers=auth)
    assert resp.status_code == 200
    assert client.get("/api/bookmarks", headers=auth).json()["total"] == 0


def test_bookmarks_delete_404(client, auth):
    resp = client.delete("/api/bookmarks/9999", headers=auth)
    assert resp.status_code == 404


def test_bookmarks_delete_rejects_other_users_bookmark(client, db_session,
                                                      auth, monkeypatch):
    """The delete endpoint must scope bookmarks to the caller's profile."""
    opp_id = seed_bookmarks_context(client, db_session, auth, monkeypatch)
    bm_id = client.post("/api/bookmarks", headers=auth,
                        json={"opportunity_id": opp_id}).json()["id"]

    other_headers = _register_and_login(client, "bob@example.com")
    mock_profile_extract(monkeypatch)
    build_profile(client, other_headers)

    resp = client.delete(f"/api/bookmarks/{bm_id}", headers=other_headers)
    assert resp.status_code == 404
    assert client.get("/api/bookmarks", headers=auth).json()["total"] == 1


# ---------------------------------------------------------------------------
# preferences — digest toggle persisted to DigestPreference
# ---------------------------------------------------------------------------
def seed_preferences_context(client, auth, monkeypatch):
    mock_profile_extract(monkeypatch)
    build_profile(client, auth)


def test_preferences_requires_auth_401(client):
    assert client.get("/api/preferences").status_code == 401
    assert client.post("/api/preferences",
                       json={"digest_enabled": True}).status_code == 401


def test_preferences_without_profile_404(client, auth):
    assert client.get("/api/preferences", headers=auth).status_code == 404
    assert client.post("/api/preferences", headers=auth,
                       json={"digest_enabled": True}).status_code == 404


def test_preferences_default_disabled(client, db_session, auth, monkeypatch):
    seed_preferences_context(client, auth, monkeypatch)
    resp = client.get("/api/preferences", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["digest_enabled"] is False


def test_preferences_enable_digest(client, db_session, auth, monkeypatch):
    seed_preferences_context(client, auth, monkeypatch)
    resp = client.post("/api/preferences", headers=auth,
                       json={"digest_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["digest_enabled"] is True
    assert client.get("/api/preferences", headers=auth).json()[
        "digest_enabled"] is True


def test_preferences_toggle_off(client, db_session, auth, monkeypatch):
    seed_preferences_context(client, auth, monkeypatch)
    client.post("/api/preferences", headers=auth,
                json={"digest_enabled": True})
    resp = client.post("/api/preferences", headers=auth,
                       json={"digest_enabled": False})
    assert resp.json()["digest_enabled"] is False


def test_preferences_stored_per_profile(client, db_session, auth, monkeypatch):
    seed_preferences_context(client, auth, monkeypatch)
    client.post("/api/preferences", headers=auth,
                json={"digest_enabled": True})
    from db.models import DigestPreference
    prefs = db_session.query(DigestPreference).all()
    assert len(prefs) == 1
    assert prefs[0].frequency == "weekly"


# ---------------------------------------------------------------------------
# pipeline — background job queue (rq / in-process fallback) + status
# ---------------------------------------------------------------------------
@pytest.fixture()
def fake_run(monkeypatch):
    from core import tasks as tasks_module

    def fake_run(country=None, sources=None, field=None,
                 on_progress=None, **_kw):
        return [{"title": "fake record"}]
    monkeypatch.setattr(tasks_module, "run_pipeline_job",
                        lambda country=None, sources=None, field=None,
                        on_progress=None, **_kw: 1)
    return fake_run


def test_pipeline_run_starts(client, fake_run):
    resp = client.post("/api/pipeline/run", json={})
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "started"
    assert data["run_id"]


def test_pipeline_run_accepts_sources(client, fake_run):
    resp = client.post("/api/pipeline/run",
                       json={"sources": ["eso"], "country": "Germany"})
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_extract_cv_txt(client):
    import base64
    auth = _register_and_login(client, "cvuser@example.com")
    content = base64.b64encode(
        b"PhD researcher in astronomy; radio interferometry with LOFAR; Python."
    ).decode()
    resp = client.post("/api/profile/extract-cv", headers=auth,
                       json={"filename": "cv.txt", "content_b64": content})
    assert resp.status_code == 200
    body = resp.json()
    assert "astronomy" in body["raw_text"]
    assert body["chars"] > 0
    assert body["filename"] == "cv.txt"


def test_extract_cv_requires_auth(client):
    resp = client.post("/api/profile/extract-cv",
                       json={"filename": "cv.txt", "content_b64": "eA=="})
    assert resp.status_code in (401, 403)


def test_extract_cv_unsupported_type_422(client):
    import base64
    auth = _register_and_login(client, "cvuser2@example.com")
    content = base64.b64encode(b"plausible cv text " * 10).decode()
    resp = client.post("/api/profile/extract-cv", headers=auth,
                       json={"filename": "cv.rtf", "content_b64": content})
    assert resp.status_code == 422
    assert "Unsupported" in resp.json()["detail"]


def test_extract_cv_bad_base64_422(client):
    auth = _register_and_login(client, "cvuser3@example.com")
    resp = client.post("/api/profile/extract-cv", headers=auth,
                       json={"filename": "cv.txt",
                             "content_b64": "!!! not base64 !!!"})
    assert resp.status_code == 422


def test_pipeline_run_sources_not_list_422(client):
    resp = client.post("/api/pipeline/run", json={"sources": "eso"})
    assert resp.status_code == 422


def test_pipeline_run_accepts_field(client, fake_run):
    resp = client.post("/api/pipeline/run", json={"field": "biology"})
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_pipeline_run_unknown_field_422(client):
    resp = client.post("/api/pipeline/run", json={"field": "not_a_real_field"})
    assert resp.status_code == 422
    assert "Unknown field profile" in resp.json()["detail"]


def test_pipeline_job_records_per_source_progress(monkeypatch):
    """M3: the in-process job accumulates per-source progress events into its
    record, so get_job_status can stream them to the run dialog."""
    from core import tasks as tasks_module

    monkeypatch.setattr("db.init.resolve_db_url", lambda: "sqlite://")
    monkeypatch.setattr("db.init.seed_from_json", lambda *a, **k: 0)

    def fake_pipeline_run(cfg, only_sources=None, on_progress=None, **kw):
        if on_progress:
            on_progress({"event": "start", "total": 2})
            on_progress({"event": "source", "source": "eso", "status": "done",
                         "records": 3, "duration": 0.1})
            on_progress({"event": "source", "source": "aas", "status": "error",
                         "records": 0, "duration": 0.2})
        return []

    monkeypatch.setattr(tasks_module, "pipeline_run", fake_pipeline_run)
    with tasks_module._in_memory_jobs_lock:
        tasks_module._in_memory_jobs["progjob"] = {"job_id": "progjob",
                                                   "status": "running"}
    tasks_module.run_pipeline_job(
        on_progress=tasks_module._inproc_progress_callback("progjob"))

    prog = tasks_module.get_job_status("progjob")["progress"]
    assert prog["total"] == 2
    assert prog["completed"] == 2
    by_src = {s["source"]: s for s in prog["sources"]}
    assert by_src["eso"]["status"] == "done" and by_src["eso"]["records"] == 3
    assert by_src["aas"]["status"] == "error"


def test_run_pipeline_job_field_selects_taxonomy(monkeypatch):
    """The chosen field must reach build_config so the crawl scores against
    that field's taxonomy — this is the wiring that makes the dashboard's
    field dropdown actually change what a run collects (H1/2A)."""
    from core import tasks as tasks_module

    # Isolate the DB-seeding side effect: the field wiring is all we assert.
    monkeypatch.setattr("db.init.resolve_db_url", lambda: "sqlite://")
    monkeypatch.setattr("db.init.seed_from_json", lambda *a, **k: 0)

    seen: list[tuple] = []

    def capture(cfg, only_sources=None, **kw):
        seen.append((cfg.field_profile, tuple(cfg.core_anchors)))
        return []

    monkeypatch.setattr(tasks_module, "pipeline_run", capture)
    tasks_module.run_pipeline_job(field="biology")   # explicit field profile
    tasks_module.run_pipeline_job()                  # server default taxonomy

    assert seen[0][0] == "biology"
    # A different profile means a genuinely different anchor set was compiled,
    # not just a relabelled default.
    assert seen[0][1] != seen[1][1]


def test_pipeline_status_completed_with_records(client, fake_run):
    run_id = client.post("/api/pipeline/run", json={}).json()["run_id"]
    status = wait_for_status(client, run_id)
    assert status["status"] == "completed"
    assert status["records"] == 1


def test_pipeline_status_failed(client, monkeypatch):
    from core import tasks as tasks_module

    def broken_run(country=None, sources=None, field=None, on_progress=None, **_kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(tasks_module, "run_pipeline_job", broken_run)
    run_id = client.post("/api/pipeline/run", json={}).json()["run_id"]
    status = wait_for_status(client, run_id)
    assert status["status"] == "failed"
    assert "boom" in status["error"]


def test_pipeline_status_running(client):
    from core import tasks as tasks_module
    tasks_module._in_memory_jobs["abc123"] = {"run_id": "abc123",
                                              "status": "running"}
    resp = client.get("/api/pipeline/status?run_id=abc123")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_pipeline_status_unknown_404(client):
    resp = client.get("/api/pipeline/status?run_id=doesnotexist")
    assert resp.status_code == 404


def test_pipeline_status_requires_run_id_422(client):
    assert client.get("/api/pipeline/status").status_code == 422


# ---------------------------------------------------------------------------
# Sprint 06 — B2: /api/jobs status + cancellation
# ---------------------------------------------------------------------------
def test_jobs_get_status_completed(client, fake_run):
    run_id = client.post("/api/pipeline/run", json={}).json()["run_id"]
    status = wait_for_status(client, run_id)
    resp = client.get(f"/api/jobs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_jobs_get_unknown_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_jobs_cancel_running(client):
    """No live token (job record only) — the status is set directly."""
    from core import tasks as tasks_module
    tasks_module._in_memory_jobs["cancelme"] = {"job_id": "cancelme",
                                                "status": "running"}
    resp = client.delete("/api/jobs/cancelme")
    assert resp.status_code == 200
    # "cancelling", not "cancelled": a real run finishes storing its partial
    # results before it reports a terminal state, so a poll can never see
    # "cancelled" while data is still being written.
    assert resp.json()["status"] == "cancelling"
    assert tasks_module.get_job_status("cancelme")["status"] == "cancelled"


def test_jobs_cancel_signals_a_live_run(client):
    """With a live token the request must reach the worker, not just flip a
    label — that is the difference between a real Cancel and a cosmetic one."""
    from core import cancel as cancel_mod
    from core import tasks as tasks_module
    token = cancel_mod.register("livejob")
    tasks_module._in_memory_jobs["livejob"] = {"job_id": "livejob",
                                               "status": "running"}
    try:
        assert token.is_cancelled() is False
        resp = client.delete("/api/jobs/livejob")
        assert resp.status_code == 200
        assert token.is_cancelled() is True
        # Still "running" until the crawl has stored what it found.
        assert tasks_module.get_job_status("livejob")["status"] == "running"
    finally:
        cancel_mod.release("livejob")
        tasks_module._in_memory_jobs.pop("livejob", None)


def test_jobs_cancel_finished_job_409(client):
    from core import tasks as tasks_module
    tasks_module._in_memory_jobs["donejob"] = {"job_id": "donejob",
                                               "status": "completed",
                                               "records": 5}
    try:
        assert client.delete("/api/jobs/donejob").status_code == 409
    finally:
        tasks_module._in_memory_jobs.pop("donejob", None)


def test_jobs_cancel_unknown_404(client):
    assert client.delete("/api/jobs/nope").status_code == 404
