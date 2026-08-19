"""tests.test_auth_flow — Sprint 07, Track B2.

Covers the password-reset and email-verification flow: identical responses
whether or not the email exists (no enumeration), single-use + expiring reset
tokens, password rotation, verification, and re-send. Emails are never really
sent (dev-mode logging keeps the suite offline).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import (generate_secure_token, hash_password, hash_token,
                          login_limiter, register_limiter, reset_limiter,
                          verify_limiter)
from db.models import Base, EmailVerification, PasswordReset, User
from db.repositories import UserRepo

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset():
    for limiter in (register_limiter, login_limiter, reset_limiter,
                    verify_limiter):
        limiter.clear("testclient")
    from core import tasks
    tasks._in_memory_jobs.clear()
    yield
    for limiter in (register_limiter, login_limiter, reset_limiter,
                    verify_limiter):
        limiter.clear("testclient")


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
    def override():
        yield db_session
    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _register(client, email="flow@example.com"):
    client.post("/api/auth/register",
                json={"email": email, "password": PASSWORD})


def _make_reset(session, user_id, *, expired=False, used=False):
    token = generate_secure_token()
    now = datetime.now(timezone.utc)
    row = PasswordReset(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=now - timedelta(hours=1) if expired else now
        + timedelta(hours=24),
    )
    if used:
        row.used_at = now
    session.add(row)
    session.commit()
    return token


# --- forgot-password ------------------------------------------------------------
def test_forgot_password_identical_response_known_and_unknown(client,
                                                              db_session):
    _register(client)
    user = UserRepo(db_session).get_by_email("flow@example.com")
    assert user is not None
    known = client.post("/api/auth/forgot-password",
                        json={"email": "flow@example.com"})
    unknown = client.post("/api/auth/forgot-password",
                          json={"email": "nobody@example.com"})
    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == unknown.json()


def test_forgot_password_creates_hashed_token(client, db_session):
    _register(client)
    client.post("/api/auth/forgot-password",
                json={"email": "flow@example.com"})
    row = db_session.scalar(select(PasswordReset))
    assert row is not None
    assert len(row.token_hash) == 64  # SHA-256 hex
    assert "=" not in row.token_hash  # hashed, never the plaintext token


def test_forgot_password_unknown_email_creates_no_token(client, db_session):
    resp = client.post("/api/auth/forgot-password",
                       json={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert db_session.scalar(select(PasswordReset)) is None


# --- reset-password ---------------------------------------------------------------
def test_reset_rotates_password_and_is_single_use(client, db_session):
    _register(client)
    user = UserRepo(db_session).get_by_email("flow@example.com")
    token = _make_reset(db_session, user.id)
    resp = client.post("/api/auth/reset-password",
                       json={"token": token,
                             "new_password": "NewPassw0rd!"})
    assert resp.status_code == 200
    row = db_session.scalar(select(PasswordReset))
    assert row.used_at is not None
    # New password works for login.
    ok = client.post("/api/auth/login",
                     json={"email": "flow@example.com",
                           "password": "NewPassw0rd!"})
    assert ok.status_code == 200
    # Old password no longer works.
    old = client.post("/api/auth/login",
                      json={"email": "flow@example.com",
                            "password": PASSWORD})
    assert old.status_code == 401
    # Second use of the same token is rejected.
    again = client.post("/api/auth/reset-password",
                        json={"token": token,
                              "new_password": "AnotherP1!"})
    assert again.status_code == 400


def test_reset_rejects_expired_token(client, db_session):
    _register(client)
    user = UserRepo(db_session).get_by_email("flow@example.com")
    token = _make_reset(db_session, user.id, expired=True)
    resp = client.post("/api/auth/reset-password",
                       json={"token": token, "new_password": "NewPassw0rd!"})
    assert resp.status_code == 400


def test_reset_rejects_unknown_token(client, db_session):
    _register(client)
    resp = client.post("/api/auth/reset-password",
                       json={"token": "bogus", "new_password": "NewPassw0rd!"})
    assert resp.status_code == 400


def test_reset_rejects_weak_password(client, db_session):
    _register(client)
    user = UserRepo(db_session).get_by_email("flow@example.com")
    token = _make_reset(db_session, user.id)
    resp = client.post("/api/auth/reset-password",
                       json={"token": token, "new_password": "weak"})
    assert resp.status_code == 422


# --- verify-email -----------------------------------------------------------------
def test_register_issues_verification_token(client, db_session):
    _register(client)
    row = db_session.scalar(select(EmailVerification))
    assert row is not None
    user = UserRepo(db_session).get_by_email("flow@example.com")
    assert user.email_verified is False


def test_verify_email_marks_user_verified(client, db_session):
    _register(client)
    user = UserRepo(db_session).get_by_email("flow@example.com")
    row = db_session.scalar(select(EmailVerification))
    resp = client.post("/api/auth/verify-email", json={"token": "bogus"})
    assert resp.status_code == 400
    # Read the plaintext token back out of the row: create a fresh row.
    token = generate_secure_token()
    db_session.add(EmailVerification(
        user_id=user.id, token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)))
    db_session.commit()
    resp = client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200
    db_session.refresh(user)
    assert user.email_verified is True
    assert user.email_verified_at is not None
    # Single-use.
    again = client.post("/api/auth/verify-email", json={"token": token})
    assert again.status_code == 400


def test_resend_verification_identical_for_known_and_unknown(client,
                                                             db_session):
    _register(client)
    known = client.post("/api/auth/resend-verification",
                        json={"email": "flow@example.com"})
    unknown = client.post("/api/auth/resend-verification",
                          json={"email": "nobody@example.com"})
    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == unknown.json()
    # New token issued for the real unverified account.
    assert db_session.scalar(select(EmailVerification)).used_at is None


# --- audit rows -------------------------------------------------------------------
def test_audit_rows_written_for_auth_flow(client, db_session):
    from db.models import AuditEvent
    _register(client)
    client.post("/api/auth/forgot-password",
                json={"email": "flow@example.com"})
    actions = list(db_session.scalars(select(AuditEvent.action)))
    assert "auth.register" in actions
    assert "auth.forgot_password" in actions
    login = client.post("/api/auth/login",
                        json={"email": "flow@example.com",
                              "password": "wrongpass"})
    assert login.status_code == 401
    actions = list(db_session.scalars(select(AuditEvent.action)))
    assert "auth.login_failed" in actions
