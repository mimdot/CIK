"""tests.test_v1_api — Sprint 08, Track B4 (public API auth + limits).

Covers the envelope/error contract of /api/v1, API-key vs JWT auth, scope
enforcement (403), revoked/expired/bad-prefix keys (401), per-key rate limit
and daily quota (429 with headers), and that the internal routes are
unaffected (regression).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import _IP_LIMITER, _KEY_LIMITERS, _TOUCH, get_db
from api.security import create_access_token, login_limiter, register_limiter
from core import ratelimit
from core.ratelimit import api_key_meter
from db.models import ApiKey, Base, Opportunity, User
from db.repositories import ApiKeyRepo, UserRepo

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset_limits():
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    _IP_LIMITER.clear()
    _KEY_LIMITERS.clear()
    _TOUCH.clear()
    with ratelimit._IN_MEMORY_LOCK:
        ratelimit._IN_MEMORY.clear()
    api_key_meter.clear()
    yield
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    _IP_LIMITER.clear()
    _KEY_LIMITERS.clear()
    _TOUCH.clear()
    with ratelimit._IN_MEMORY_LOCK:
        ratelimit._IN_MEMORY.clear()
    api_key_meter.clear()


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
def user_headers(client, db_session):
    email = "api@example.com"
    client.post("/api/auth/register", json={"email": email,
                                            "password": PASSWORD})
    tok = create_access_token(UserRepo(db_session).get_by_email(email).id)
    return {"Authorization": f"Bearer {tok}"}


def _create_key(client, user_headers, **kwargs):
    body = {"name": kwargs.pop("name", "t")}
    if "scopes" in kwargs:
        body["scopes"] = kwargs["scopes"]
    return client.post("/api/v1/apikeys", json=body, headers=user_headers)


def _single_key(db_session) -> ApiKey:
    return db_session.scalar(select(ApiKey))


def _key_headers(client, user_headers, **kwargs) -> dict:
    raw = _create_key(client, user_headers, **kwargs).json()["raw_key"]
    return {"Authorization": f"Bearer {raw}"}


# --- auth ----------------------------------------------------------------------
def test_v1_me_with_api_key(client, user_headers):
    headers = _key_headers(client, user_headers, scopes=["read:profile"])
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 200
    assert "data" in resp.json()
    assert resp.headers["X-RateLimit-Limit"] == "60"


def test_v1_me_with_user_jwt(client, user_headers):
    resp = client.get("/api/v1/me", headers=user_headers)
    assert resp.status_code == 200
    assert "data" in resp.json()


def test_v1_me_requires_auth(client):
    assert client.get("/api/v1/me").status_code == 401


def test_v1_bad_prefix_401(client):
    resp = client.get("/api/v1/me",
                      headers={"Authorization": "Bearer cik_" + "ab" * 20})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "http_error"


def test_v1_revoked_key_401(client, user_headers, db_session):
    headers = _key_headers(client, user_headers)
    ApiKeyRepo(db_session).revoke(_single_key(db_session))
    db_session.commit()
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 401
    assert "revoked" in resp.json()["error"]["message"]


def test_v1_expired_key_401(client, user_headers, db_session):
    headers = _key_headers(client, user_headers)
    key = _single_key(db_session)
    key.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 401
    assert "expired" in resp.json()["error"]["message"]


# --- scopes --------------------------------------------------------------------
def test_v1_missing_scope_403(client, user_headers):
    headers = _key_headers(client, user_headers, scopes=["read:matches"])
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 403
    assert "read:profile" in resp.json()["error"]["message"]


def test_v1_wrong_write_scope_403(client, user_headers, db_session):
    db_session.add(Opportunity(source="a", source_raw="u1", title="T",
                               country="DE", url="https://ex.org/1"))
    db_session.commit()
    # read-only key cannot write a bookmark.
    headers = _key_headers(client, user_headers, scopes=["read:profile"])
    resp = client.post("/api/v1/bookmarks", json={"opportunity_id": 1},
                       headers=headers)
    assert resp.status_code == 403


# --- limits --------------------------------------------------------------------
def test_v1_rate_limit_429_with_headers(client, user_headers, db_session):
    headers = _key_headers(client, user_headers, scopes=["read:profile"])
    key = _single_key(db_session)
    ApiKeyRepo(db_session).set_limits(key, quota_limit=None, rate_limit=2)
    db_session.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    blocked = client.get("/api/v1/me", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == "2"
    assert "Retry-After" in blocked.headers


def test_v1_quota_429_with_retry_after(client, user_headers, db_session):
    headers = _key_headers(client, user_headers, scopes=["read:profile"])
    key = _single_key(db_session)
    ApiKeyRepo(db_session).set_limits(key, quota_limit=1, rate_limit=None)
    db_session.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    blocked = client.get("/api/v1/me", headers=headers)
    assert blocked.status_code == 429
    assert "quota" in blocked.json()["error"]["message"]
    assert int(blocked.headers["Retry-After"]) > 0


# --- envelope + internal regression ----------------------------------------------
def test_v1_opportunities_envelope(client, user_headers, db_session):
    headers = _key_headers(client, user_headers, scopes=["read:opportunities"])
    db_session.add(Opportunity(source="euraxess", source_raw="u1",
                               title="PhD in radio astronomy",
                               country="Germany", position_type="phd",
                               url="https://ex.org/1"))
    db_session.commit()
    resp = client.get("/api/v1/opportunities", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and "meta" in body
    assert body["meta"]["total"] == 1
    assert body["data"][0]["title"] == "PhD in radio astronomy"


def test_v1_validation_error_envelope(client, user_headers):
    headers = _key_headers(client, user_headers, scopes=["write:bookmarks"])
    resp = client.post("/api/v1/bookmarks", json={"opportunity_id": "nope"},
                       headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_internal_routes_keep_default_error_shape(client, user_headers,
                                                 db_session):
    """Internal (versionless) routes are untouched: /api/profile 404s with the
    default {"detail": ...} shape, not the v1 envelope."""
    resp = client.get("/api/profile", headers=user_headers)
    assert resp.status_code in (200, 404)
    if resp.status_code == 404:
        assert "detail" in resp.json()
        assert "error" not in resp.json()


def test_rollup_persists_meter_into_usage_rows(client, user_headers,
                                               db_session):
    """Nightly rollup copies live meter counters into api_key_usage rows."""
    from datetime import datetime, timezone
    from core.tasks import rollup_api_key_usage
    from db.repositories import ApiKeyUsageRepo
    headers = _key_headers(client, user_headers, scopes=["read:profile"])
    key = _single_key(db_session)
    for _ in range(3):
        assert client.get("/api/v1/me", headers=headers).status_code == 200
    written = rollup_api_key_usage(session=db_session)
    assert written >= 1
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = ApiKeyUsageRepo(db_session).get_usage(key.id, day)
    assert row is not None
    assert row.requests >= 3