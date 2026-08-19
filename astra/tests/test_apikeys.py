"""tests.test_apikeys — Sprint 08, Track A2 (key lifecycle) + admin surface.

Covers create/list/patch/revoke/rotate/usage for a developer's own keys, the
one-time raw-key contract (sha256(raw) persisted, prefix badge only), scope
validation, and the admin list/revoke/limits endpoints.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import create_access_token, login_limiter, register_limiter
from db.models import ApiKey, Base, User
from db.repositories import ApiKeyRepo, UserRepo

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
    token = create_access_token(UserRepo(db_session).get_by_email(email).id)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(db_session):
    admin = UserRepo(db_session).create("root@example.com", "x", role="admin")
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _create_key(client, headers, **kw):
    body = {"name": kw.pop("name", "CI bot")}
    if kw.get("scopes") is not None:
        body["scopes"] = kw["scopes"]
    if kw.get("expires_at"):
        body["expires_at"] = kw["expires_at"]
    return client.post("/api/v1/apikeys", json=body, headers=headers)


# --- lifecycle ----------------------------------------------------------------
def test_create_returns_raw_key_once_with_prefix(client, auth_headers,
                                                 db_session):
    resp = _create_key(client, auth_headers, name="Production app")
    assert resp.status_code == 201
    data = resp.json()
    raw = data["raw_key"]
    assert raw.startswith("cik_") and len(raw) == 44  # cik_ + 40 hex
    assert data["key_prefix"] == raw[:12]
    assert data["scopes"] == ["read:profile", "read:matches",
                              "read:opportunities", "read:supervisors"]
    # Only the SHA-256 hash is persisted — never the raw key.
    from sqlalchemy import select
    row = db_session.scalar(select(ApiKey))
    assert row.key_hash == hashlib.sha256(raw.encode()).hexdigest()


def test_list_shows_keys_without_hash(client, auth_headers, db_session):
    _create_key(client, auth_headers, name="one")
    _create_key(client, auth_headers, name="two")
    resp = client.get("/api/v1/apikeys", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert "raw_key" not in item
        assert "key_hash" not in item
        assert item["key_prefix"].startswith("cik_")


def test_create_with_custom_scopes_and_expiry(client, auth_headers, db_session):
    resp = _create_key(client, auth_headers, name="ml", scopes=["read:matches"])
    assert resp.status_code == 201
    assert resp.json()["scopes"] == ["read:matches"]


def test_create_rejects_admin_scope_and_unknown_scope(client, auth_headers):
    bad_admin = _create_key(client, auth_headers, scopes=["admin"])
    assert bad_admin.status_code == 422
    bad_unknown = _create_key(client, auth_headers, scopes=["read:secrets"])
    assert bad_unknown.status_code == 422


def test_create_rejects_past_expiry(client, auth_headers):
    resp = _create_key(client, auth_headers, expires_at="2020-01-01T00:00:00Z")
    assert resp.status_code == 422


def test_requires_auth(client):
    assert client.get("/api/v1/apikeys").status_code == 401
    assert _create_key(client, {}).status_code == 401


def test_patch_renames_and_changes_scopes(client, auth_headers, db_session):
    key_id = _create_key(client, auth_headers).json()["id"]
    resp = client.patch(f"/api/v1/apikeys/{key_id}",
                        json={"name": "renamed",
                              "scopes": ["read:opportunities"]},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    assert resp.json()["scopes"] == ["read:opportunities"]


def test_delete_revokes_and_then_conflicts(client, auth_headers):
    key_id = _create_key(client, auth_headers).json()["id"]
    first = client.delete(f"/api/v1/apikeys/{key_id}", headers=auth_headers)
    assert first.status_code == 200
    assert first.json()["status"] == "revoked"
    again = client.delete(f"/api/v1/apikeys/{key_id}", headers=auth_headers)
    assert again.status_code == 409


def test_rotate_issues_new_key_and_revokes_old(client, auth_headers,
                                               db_session):
    created = _create_key(client, auth_headers, name="bot",
                          scopes=["write:bookmarks"]).json()
    old_id = created["id"]
    resp = client.post(f"/api/v1/apikeys/{old_id}/rotate",
                       headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] != old_id
    assert data["raw_key"].startswith("cik_")
    assert data["name"] == "bot"
    assert data["scopes"] == ["write:bookmarks"]
    old = ApiKeyRepo(db_session).get_by_id(old_id)
    assert old.revoked_at is not None
    assert old.key_hash != hashlib.sha256(data["raw_key"].encode()).hexdigest()


def test_cannot_touch_another_users_key(client, auth_headers, db_session):
    key_id = _create_key(client, auth_headers).json()["id"]
    other = UserRepo(db_session).create("other@example.com", "x")
    db_session.commit()
    other_headers = {"Authorization": f"Bearer {create_access_token(other.id)}"}
    assert client.get(f"/api/v1/apikeys/{key_id}/usage",
                      headers=other_headers).status_code == 404
    assert client.delete(f"/api/v1/apikeys/{key_id}",
                         headers=other_headers).status_code == 404


def test_usage_returns_quota_and_dates(client, auth_headers, db_session):
    key_id = _create_key(client, auth_headers).json()["id"]
    ApiKeyUsageRepo = __import__("db.repositories",
                                 fromlist=["ApiKeyUsageRepo"]).ApiKeyUsageRepo
    ApiKeyUsageRepo(db_session).upsert_usage(key_id, "2026-08-07", 12)
    ApiKeyUsageRepo(db_session).upsert_usage(key_id, "2026-08-08", 3,
                                             rate_limited=1)
    db_session.commit()
    resp = client.get(f"/api/v1/apikeys/{key_id}/usage", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["quota_limit"] is None
    assert data["items"][0]["date"] == "2026-08-08"
    assert data["items"][0]["requests"] == 3


# --- admin surface ------------------------------------------------------------
def test_admin_list_requires_admin(client, auth_headers):
    assert client.get("/api/admin/apikeys", headers=auth_headers).status_code \
        == 403


def test_admin_lists_revokes_and_overrides(client, auth_headers, db_session):
    key_id = _create_key(client, auth_headers, name="victim").json()["id"]
    headers = _admin_headers(db_session)
    listed = client.get("/api/admin/apikeys", headers=headers)
    assert listed.status_code == 200
    assert any(i["id"] == key_id for i in listed.json()["items"])
    assert listed.json()["items"][0]["user_email"] == "dev@example.com"

    over = client.patch(f"/api/admin/apikeys/{key_id}/limits",
                        json={"quota_limit": 5000, "rate_limit": 120},
                        headers=headers)
    assert over.status_code == 200
    assert over.json()["quota_limit"] == 5000
    assert over.json()["rate_limit"] == 120

    revoked = client.post(f"/api/admin/apikeys/{key_id}/revoke",
                          headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert ApiKeyRepo(db_session).get_by_id(key_id).revoked_at is not None
