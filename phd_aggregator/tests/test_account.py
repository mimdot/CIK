"""tests.test_account — Sprint 10, D2 data-subject endpoints.

Covers the GDPR surface: data export, consent read/update, and right-to-
erasure. Erasure hard-deletes the user's own PII and anonymizes analytics
rows (feedback / LLM usage / audit trail keep their rows but lose the link),
which is the documented policy.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import create_access_token, login_limiter, register_limiter
from db.models import (ApiKey, AuditEvent, Base, LlmUsage, Match,
                       MatchFeedback, User, UserProfileRow)
from db.repositories import UserRepo


PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    from core import cache
    cache.invalidate("")
    yield
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")


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
def auth_headers(client, db_session):
    email = "dev@example.com"
    client.post("/api/auth/register",
                json={"email": email, "password": PASSWORD})
    user = UserRepo(db_session).get_by_email(email)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _seed_user_data(db_session):
    """Profile + match + feedback + LLM usage + key rows owned by dev@example.com."""
    user = UserRepo(db_session).get_by_email("dev@example.com")
    profile = UserProfileRow(user_id=user.id, raw_text="my CV", domain="physics")
    db_session.add(profile)
    db_session.flush()
    match = Match(profile_id=profile.id, target_type="opportunity",
                  overall_score=0.9)
    db_session.add(match)
    db_session.flush()
    db_session.add(MatchFeedback(user_id=user.id, match_id=match.id,
                                 helpful=True, comment="great"))
    db_session.add(LlmUsage(user_id=user.id, feature="assistant",
                            model="gpt-4o-mini", prompt_tokens=10,
                            completion_tokens=5))
    db_session.add(AuditEvent(actor_type="user", actor_id=user.id,
                              action="register"))
    db_session.add(ApiKey(user_id=user.id, name="bot", key_hash="h" * 64,
                          key_prefix="cik_abc123"))
    db_session.commit()


# --- data export --------------------------------------------------------------
def test_export_requires_auth(client):
    assert client.get("/api/account/data-export").status_code == 401


def test_data_export_returns_all_user_scoped_data(client, auth_headers,
                                                  db_session):
    _seed_user_data(db_session)
    resp = client.get("/api/account/data-export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["account"]["email"] == "dev@example.com"
    assert data["profiles"][0]["raw_text"] == "my CV"
    assert data["matches"][0]["overall_score"] == 0.9
    assert data["feedback"][0]["comment"] == "great"
    assert data["api_keys"][0]["name"] == "bot"
    assert "key_hash" not in data["api_keys"][0]
    assert data["llm_usage"][0]["feature"] == "assistant"
    assert any(a["action"] == "register" for a in data["audit_trail"])


def test_data_export_does_not_leak_other_user(client, auth_headers, db_session):
    _seed_user_data(db_session)
    other = UserRepo(db_session).create("other@example.com", "x")
    db_session.commit()
    db_session.add(LlmUsage(user_id=other.id, feature="digest",
                            model="m", prompt_tokens=1, completion_tokens=1))
    db_session.commit()
    data = client.get("/api/account/data-export", headers=auth_headers).json()
    assert all(u["feature"] != "digest" for u in data["llm_usage"])


# --- consent ------------------------------------------------------------------
def test_consent_defaults_to_null(client, auth_headers):
    resp = client.get("/api/account/consent", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["marketing_email"] is None


def test_consent_update_and_read(client, auth_headers, db_session):
    resp = client.put("/api/account/consent",
                      json={"marketing_email": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["marketing_email"] is True
    assert resp.json()["updated_at"] is not None
    again = client.get("/api/account/consent", headers=auth_headers)
    assert again.json()["marketing_email"] is True


def test_consent_requires_bool(client, auth_headers):
    assert client.put("/api/account/consent",
                      json={"marketing_email": {"nested": True}},
                      headers=auth_headers).status_code == 422
    assert client.put("/api/account/consent", json={"marketing_email": 2},
                      headers=auth_headers).status_code == 422


def test_consent_is_audited(client, auth_headers, db_session):
    client.put("/api/account/consent", json={"marketing_email": False},
               headers=auth_headers)
    actions = db_session.scalars(select(AuditEvent.action)).all()
    assert "account.consent" in actions


# --- right to erasure ---------------------------------------------------------
def test_delete_requires_auth(client):
    assert client.delete("/api/account").status_code == 401


def test_delete_hard_deletes_pii_and_anonymizes_analytics(client, auth_headers,
                                                          db_session):
    _seed_user_data(db_session)
    resp = client.delete("/api/account", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "deleted"
    assert "profiles" in body["deleted"] and "user" in body["deleted"]
    assert {"match_feedback", "llm_usage", "audit_events"} <= set(
        body["anonymized"])

    users = db_session.scalars(select(User)).all()
    assert all(u.email != "dev@example.com" for u in users)
    assert db_session.scalars(select(UserProfileRow)).all() == []
    assert db_session.scalars(select(Match)).all() == []

    # analytics rows survive but are anonymized
    fb = db_session.scalars(select(MatchFeedback)).all()
    assert len(fb) == 1 and fb[0].user_id is None
    lu = db_session.scalars(select(LlmUsage)).all()
    assert len(lu) == 1 and lu[0].user_id is None
    ae = db_session.scalars(select(AuditEvent)).all()
    assert any(a.actor_id is None and a.action == "register" for a in ae)


def test_delete_logs_account_delete_audit(client, auth_headers, db_session):
    client.delete("/api/account", headers=auth_headers)
    actions = db_session.scalars(select(AuditEvent.action)).all()
    assert "account.delete" in actions


def test_erased_user_cannot_authenticate_again(client, auth_headers, db_session):
    client.delete("/api/account", headers=auth_headers)
    # stale token now resolves to no user -> 401
    assert client.get("/api/account/data-export",
                      headers=auth_headers).status_code == 401
