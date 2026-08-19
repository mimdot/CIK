"""tests.test_cv_feature_flag — CV reading switched off (Issue 3).

The point of the flag is that no user spends AI tokens before we are ready, so
the load-bearing test here is the negative one: with the feature off, nothing
in this router constructs an LLM router or issues a provider request — not even
via /build, which stays reachable because the keyword picker depends on it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.routes.profile as profile_routes
from api.app import app
from api.deps import get_current_user, get_db
from db.models import Base, User
from db.repositories import UserRepo

# What the keyword picker sends to /build for a brand-new user with no profile
# row yet (see handleSaveKeywords in dashboard/app/(app)/profile/page.tsx).
PICKER_SEED = ("Research field: astronomy. Keywords: astronomy, "
               "interstellar medium, radio astronomy.")


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
def user(db_session) -> User:
    return UserRepo(db_session).create("cv@example.com", "x")


@pytest.fixture()
def client(db_session, user):
    def db_override():
        yield db_session

    def user_override():
        return user

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = user_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def cv_off(monkeypatch):
    monkeypatch.setenv("CV_PARSING_ENABLED", "0")


@pytest.fixture()
def cv_on(monkeypatch):
    monkeypatch.setenv("CV_PARSING_ENABLED", "1")


@pytest.fixture()
def no_llm(monkeypatch):
    """Make any attempt to build an LLM router a loud test failure."""
    def boom(*_a, **_kw):
        raise AssertionError(
            "an AI provider was reached while CV parsing was disabled")

    monkeypatch.setattr(profile_routes, "LLMRouter", boom)
    monkeypatch.setattr(profile_routes, "extract_profile", boom)


# --- switched off ---------------------------------------------------------------

def test_upload_is_refused_with_a_reason_not_an_error(client, cv_off):
    r = client.post("/api/profile/extract-cv",
                    json={"filename": "cv.txt", "content_b64": "aGk="})
    assert r.status_code == 503
    assert "future update" in r.json()["detail"]


def test_analyse_is_refused(client, cv_off):
    r = client.post("/api/profile/analyse-cv", json={"raw_text": "astronomy"})
    assert r.status_code == 503


def test_parser_support_reports_disabled(client, cv_off):
    assert client.get("/api/profile/parser-support").json()["enabled"] is False


def test_build_never_touches_an_ai_provider(client, cv_off, no_llm):
    """The load-bearing one: /build stays open but must not call out."""
    r = client.post("/api/profile/build", json={"raw_text": PICKER_SEED})
    assert r.status_code == 201, r.text


def test_keyword_picker_can_still_create_a_first_profile(client, cv_off, no_llm):
    r = client.post("/api/profile/build", json={"raw_text": PICKER_SEED})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == "astronomy"
    assert body["skills"], "the picker's keywords must survive into the profile"


def test_profile_is_readable_after_the_picker_created_it(client, cv_off, no_llm):
    client.post("/api/profile/build", json={"raw_text": PICKER_SEED})
    assert client.get("/api/profile").status_code == 200


# --- switched back on -----------------------------------------------------------

def test_re_enabling_restores_the_endpoints(client, cv_on):
    """Nothing was deleted: one variable brings the whole path back."""
    assert client.get("/api/profile/parser-support").json()["enabled"] is True
    r = client.post("/api/profile/analyse-cv", json={"raw_text": "astronomy"})
    assert r.status_code == 200
