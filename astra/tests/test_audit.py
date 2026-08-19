"""tests.test_audit — Sprint 07, Tracks B4 + B5.

Verifies the audit trail: rows are written for register/login/reset/
unsubscribe/admin actions, and the admin-only viewer endpoint filters and
pages correctly (and records its own view event).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import hash_password, login_limiter, register_limiter
from db.models import AuditEvent, Base, DigestPreference, UserProfileRow
from db.repositories import UserRepo

PASSWORD = "SuperSecret1"
ADMIN_PASSWORD = "AdminSecret1"


@pytest.fixture(autouse=True)
def _reset():
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    from core import tasks
    tasks._in_memory_jobs.clear()
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
    def override():
        yield db_session
    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _register(client, email="user@example.com", password=PASSWORD):
    client.post("/api/auth/register", json={"email": email,
                                            "password": password})


def _login(client, email="user@example.com", password=PASSWORD):
    resp = client.post("/api/auth/login",
                       json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_admin(db_session, email="admin@example.com"):
    return UserRepo(db_session).create(email, hash_password(ADMIN_PASSWORD),
                                       role="admin")


def _admin_auth(client, db_session):
    _make_admin(db_session)
    resp = client.post("/api/auth/login",
                       json={"email": "admin@example.com",
                             "password": ADMIN_PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _actions(db_session) -> list[str]:
    return list(db_session.scalars(select(AuditEvent.action)))


def test_register_and_login_write_audit_rows(client, db_session):
    _register(client)
    _login(client)
    actions = _actions(db_session)
    assert "auth.register" in actions
    assert "auth.login" in actions


def test_failed_login_and_reset_write_audit_rows(client, db_session):
    _register(client)
    bad = client.post("/api/auth/login",
                      json={"email": "user@example.com", "password": "nope"})
    assert bad.status_code == 401
    client.post("/api/auth/forgot-password",
                json={"email": "user@example.com"})
    actions = _actions(db_session)
    assert "auth.login_failed" in actions
    assert "auth.forgot_password" in actions


def test_unsubscribe_writes_audit_row(client, db_session):
    _register(client)
    user = UserRepo(db_session).get_by_email("user@example.com")
    row = UserProfileRow(user_id=user.id, domain="astronomy", confidence=0.9,
                         active=True)
    db_session.add(row)
    db_session.flush()
    db_session.add(DigestPreference(profile_id=row.id, frequency="weekly"))
    db_session.commit()
    from api.security import hmac_sign
    token = hmac_sign(str(row.id))
    resp = client.get("/api/email/unsubscribe", params={"token": token})
    assert resp.status_code == 200
    assert "email.unsubscribe" in _actions(db_session)


def test_invite_create_writes_audit_row(client, db_session):
    auth = _admin_auth(client, db_session)
    resp = client.post("/api/invites", headers=auth, json={})
    assert resp.status_code == 201
    assert "admin.invite.create" in _actions(db_session)


def test_audit_view_requires_admin(client, db_session):
    _register(client)
    auth = _login(client)
    resp = client.get("/api/admin/audit", headers=auth)
    assert resp.status_code == 403


def test_audit_view_lists_and_filters(client, db_session):
    auth = _admin_auth(client, db_session)
    _register(client)
    _login(client)
    resp = client.get("/api/admin/audit", headers=auth)
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert events  # at least the admin login + view rows
    # Newest-first ordering.
    assert events == sorted(events,
                            key=lambda e: e["created_at"], reverse=True)
    # Filter by action.
    login_events = client.get("/api/admin/audit?action=auth.login",
                              headers=auth).json()["events"]
    assert login_events and all(e["action"] == "auth.login"
                                for e in login_events)
    # The viewer call itself is audited.
    assert "admin.audit_view" in _actions(db_session)
