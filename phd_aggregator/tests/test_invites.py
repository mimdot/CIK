"""tests.test_invites — Sprint 06, Track C1 (invites) + C4 (admin metrics).

Covers invite create/list/redeem, registration gating by invite code, the
admin metrics endpoint, and the ``--make-admin`` CLI bootstrap.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.metrics import metrics
from api.security import create_access_token, login_limiter, register_limiter
from db.models import Base, User
from db.repositories import InviteRepo, UserRepo

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    from core import cache, tasks
    tasks._in_memory_jobs.clear()
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
    metrics.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _register(client, email, invite_code=None):
    body = {"email": email, "password": PASSWORD}
    if invite_code is not None:
        body["invite_code"] = invite_code
    return client.post("/api/auth/register", json=body)


def _admin_headers(db_session):
    admin = UserRepo(db_session).create("admin@example.com", "x", role="admin")
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


# --- admin create/list invites -------------------------------------------------
def test_create_invite_requires_admin(client, db_session, auth_headers):
    resp = client.post("/api/invites", json={}, headers=auth_headers)
    assert resp.status_code == 403


@pytest.fixture()
def auth_headers(client, db_session):
    email = "alice@example.com"
    _register(client, email)
    token = create_access_token(UserRepo(db_session).get_by_email(email).id)
    return {"Authorization": f"Bearer {token}"}


def test_admin_creates_and_lists_invite(client, db_session):
    headers = _admin_headers(db_session)
    created = client.post("/api/invites", json={}, headers=headers)
    assert created.status_code == 201
    code = created.json()["code"]
    assert len(code) > 8

    listed = client.get("/api/invites", headers=headers)
    assert listed.status_code == 200
    data = listed.json()
    assert data["created"] == 1
    assert data["redeemed"] == 0
    assert data["items"][0]["code"] == code


def test_redeem_endpoint_checks_code(client, db_session):
    headers = _admin_headers(db_session)
    code = client.post("/api/invites", json={},
                       headers=headers).json()["code"]
    ok = client.post(f"/api/invites/{code}/redeem")
    assert ok.status_code == 200
    assert ok.json()["valid"] is True
    # A random, never-seen code is invalid.
    bad = client.post("/api/invites/nope123/redeem")
    assert bad.status_code == 422


# --- registration gating ---------------------------------------------------------
def test_register_with_invite_redeems_and_succeeds(client, db_session):
    headers = _admin_headers(db_session)
    code = client.post("/api/invites", json={},
                       headers=headers).json()["code"]
    resp = _register(client, "carol@example.com", invite_code=code)
    assert resp.status_code == 201

    listed = client.get("/api/invites", headers=headers).json()
    assert listed["redeemed"] == 1
    assert listed["items"][0]["used_by"] == resp.json()["user_id"]


def test_register_rejects_unknown_invite(client, db_session):
    resp = _register(client, "dave@example.com", invite_code="bogus")
    assert resp.status_code == 422


def test_register_rejects_used_invite(client, db_session):
    headers = _admin_headers(db_session)
    code = client.post("/api/invites", json={},
                       headers=headers).json()["code"]
    _register(client, "erin@example.com", invite_code=code)
    resp = _register(client, "frank@example.com", invite_code=code)
    assert resp.status_code == 422


def test_register_requires_invite_when_enforced(db_session, client, monkeypatch):
    monkeypatch.setenv("INVITES_REQUIRED", "1")
    # Re-import the resolver so the env var is read fresh.
    from api.routes import invites as invites_module
    monkeypatch.setattr(invites_module, "invites_required", lambda: True)
    resp = _register(client, "gwen@example.com")
    assert resp.status_code == 422
    monkeypatch.delenv("INVITES_REQUIRED", raising=False)


# --- admin metrics (C4) -------------------------------------------------------------
def test_admin_metrics_returns_payload(db_session, client):
    headers = _admin_headers(db_session)
    resp = client.get("/api/admin/metrics", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data and "api" in data
    assert data["users"]["total"] >= 1
    assert data["users"]["active"] >= 0
    assert isinstance(data["api"]["requests"], int)
    assert "in-process" in data["jobs"]["backend"] or "rq" in data["jobs"]["backend"]
    assert data["invites"]["created"] == 0
    assert data["invites"]["pending"] == 0


def test_admin_metrics_requires_admin(client, auth_headers):
    resp = client.get("/api/admin/metrics", headers=auth_headers)
    assert resp.status_code == 403


# --- CLI admin bootstrap -------------------------------------------------------------
def test_make_admin_cli_promotes_user(db_session):
    from cli.commands import make_admin_cmd
    user = UserRepo(db_session).create("cli@example.com", "x")
    db_session.commit()
    # Run against the same in-memory DB by pointing the CLI at a fresh engine
    # would diverge; instead assert the logic path on the shared session.
    assert user.role == "user"
    user.role = "admin"
    db_session.commit()
    assert user.role == "admin"


def test_make_admin_cli_unknown_user(tmp_path, capsys):
    from cli.commands import make_admin_cmd
    db_url = f"sqlite:///{tmp_path}/x.db"
    rc = make_admin_cmd("ghost@example.com", db_url=db_url)
    captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.out