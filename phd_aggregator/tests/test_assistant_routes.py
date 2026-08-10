"""tests.test_assistant_routes — Sprint 09, Track A2 (assistant API).

Covers: auth/profile/opportunity guards, the editable draft responses, the
soft per-user daily quota (429), the feature toggle (404), and the usage
endpoint. The LLM backend is stubbed at ``core.assistant._router`` so nothing
touches the network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import login_limiter, register_limiter
from core.llm import LLMRouter
from core.ratelimit import RedisRateLimiter
from db.models import Base, Opportunity, UserProfileRow

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset_limits():
    from api.routes.assistant import _assistant_limiter
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    _assistant_limiter.clear()
    yield
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    _assistant_limiter.clear()


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
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
    email = "drafter@example.com"
    client.post("/api/auth/register",
                json={"email": email, "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def profile(client, auth, monkeypatch):
    from core.profile_schema import UserProfile
    stub = UserProfile(domain="astronomy", subfield="interstellar medium",
                       methods=["radio interferometry"], tools=["LOFAR"],
                       skills=["dust polarization"],
                       experience_level="phd_student",
                       target_roles=["postdoc"],
                       countries_preferred=["Germany"], confidence=0.9,
                       raw_text="Radio interferometry CV text.")
    monkeypatch.setattr("api.routes.profile.extract_profile",
                        lambda raw_text, llm: stub)
    resp = client.post("/api/profile/build", headers=auth,
                       json={"raw_text": "Radio interferometry CV text."})
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def opp(db_session):
    row = Opportunity(source="euraxess", source_raw="https://ex.org/j/1",
                      title="PhD in radio astronomy", institution="MPIfR",
                      country="Germany", position_type="phd",
                      url="https://ex.org/j/1",
                      short_description="Doctoral project on radio "
                                        "interferometry.")
    db_session.add(row)
    db_session.flush()
    return {"id": row.id}


@pytest.fixture()
def fake_llm(monkeypatch):
    def fake_router():
        return LLMRouter(
            default_model="fake/model",
            backend=lambda model, messages, **kw: "Fake drafted text here.")
    monkeypatch.setattr("core.assistant._router", fake_router)


# --- guards -------------------------------------------------------------------
def test_cover_letter_requires_auth(client):
    assert client.post("/api/assistant/cover-letter",
                       json={"opportunity_id": 1}).status_code == 401


def test_cover_letter_requires_profile(client, auth):
    resp = client.post("/api/assistant/cover-letter",
                       json={"opportunity_id": 1}, headers=auth)
    assert resp.status_code == 404
    assert "profile" in resp.json()["detail"].lower()


def test_cover_letter_unknown_opportunity(client, profile, auth, fake_llm):
    resp = client.post("/api/assistant/cover-letter",
                       json={"opportunity_id": 9999}, headers=auth)
    assert resp.status_code == 404


def test_cover_letter_disabled_by_toggle(client, profile, opp, auth,
                                         monkeypatch):
    monkeypatch.setenv("ASSISTANT_ENABLED", "0")
    resp = client.post("/api/assistant/cover-letter",
                       json={"opportunity_id": opp["id"]}, headers=auth)
    assert resp.status_code == 404
    assert "disabled" in resp.json()["detail"].lower()


# --- drafting ------------------------------------------------------------------
def test_cover_letter_returns_editable_draft(client, profile, opp, auth,
                                             fake_llm):
    resp = client.post("/api/assistant/cover-letter",
                       json={"opportunity_id": opp["id"], "tone": "warm",
                             "length": "short"}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "Fake drafted text" in body["text"]
    assert body["model"] == "fake/model"
    assert body["token_count"] > 0


def test_application_email_returns_draft(client, profile, opp, auth, fake_llm):
    resp = client.post("/api/assistant/application-email",
                       json={"opportunity_id": opp["id"]}, headers=auth)
    assert resp.status_code == 200
    assert "Fake drafted text" in resp.json()["text"]


def test_cv_improvements_returns_suggestions(client, profile, opp, auth,
                                             fake_llm):
    resp = client.post("/api/assistant/cv-improvements", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "improvements" in body
    assert body["source"] in ("llm", "deterministic")


def test_usage_reports_quota(client, auth):
    resp = client.get("/api/assistant/usage", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 50
    assert body["remaining"] == 50
    assert body["used"] == 0


def test_quota_exceeded_returns_429(client, profile, opp, auth, fake_llm,
                                    monkeypatch):
    monkeypatch.setattr("api.routes.assistant._assistant_limiter",
                        RedisRateLimiter(0, 3600, prefix="assistant_test"))
    resp = client.post("/api/assistant/cover-letter",
                       json={"opportunity_id": opp["id"]}, headers=auth)
    assert resp.status_code == 429
    assert "limit" in resp.json()["detail"].lower()
