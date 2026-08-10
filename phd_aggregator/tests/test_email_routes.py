"""tests.test_email_routes — Sprint 07, Track A4.

Covers the email lifecycle endpoints: webhook (signature verification +
recording), unsubscribe (HMAC token round-trip), and preview-digest. Uses the
standard in-memory SQLite TestClient fixture pattern from tests/test_api.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import hmac_sign, login_limiter, register_limiter
from core import email as core_email
from db.models import Base, DigestPreference, EmailEvent, Opportunity, \
    UserProfileRow
from db.repositories import UserRepo

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset():
    from core import cache, tasks
    tasks._in_memory_jobs.clear()
    cache.invalidate("")
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")
    yield
    tasks._in_memory_jobs.clear()
    cache.invalidate("")
    register_limiter.clear("testclient")
    login_limiter.clear("testclient")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
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


def _register_and_login(client, email):
    client.post("/api/auth/register", json={"email": email,
                                            "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_digest_pref(session, user, *, email="digest@example.com",
                      frequency="weekly"):
    row = UserProfileRow(user_id=user.id, domain="interstellar medium",
                         methods='["radio interferometry"]',
                         countries_preferred='["Germany"]', confidence=0.9,
                         active=True)
    session.add(row)
    session.flush()
    session.add(DigestPreference(profile_id=row.id, email=email,
                                 frequency=frequency))
    session.commit()
    return row


def _seed_opportunity(session):
    session.add(Opportunity(source="euraxess", source_raw="u1",
                            title="PhD in interstellar medium",
                            institution="MPIfR", country="Germany",
                            short_description="Doctoral project using "
                            "radio interferometry on the ISM.",
                            url="https://ex.org/j/1", position_type="phd"))
    session.commit()


# --- webhook -----------------------------------------------------------------
def test_webhook_records_bounce(db_session, client):
    resp = client.post("/api/email/webhook",
                       json={"type": "email.bounced", "email": "b@x.com",
                             "id": "msg1", "data": {"bounce": 1}})
    assert resp.status_code == 200
    event = db_session.scalar(select(EmailEvent))
    assert event.event_type == "bounced"
    assert event.email_to == "b@x.com"
    assert event.provider_id == "msg1"


def test_webhook_ignores_non_bounce_events(db_session, client):
    resp = client.post("/api/email/webhook",
                       json={"type": "email.delivered", "email": "b@x.com"})
    assert resp.status_code == 200
    assert db_session.scalar(select(EmailEvent)) is None


def test_webhook_rejects_bad_signature_when_secret_set(monkeypatch, client):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "secret")
    resp = client.post("/api/email/webhook",
                       json={"type": "email.bounced", "email": "b@x.com"})
    assert resp.status_code == 401


def test_webhook_accepts_valid_signature_when_secret_set(monkeypatch,
                                                         db_session, client):
    import base64
    import hmac as hmac_mod
    import hashlib
    import time
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "secret")
    ts = str(int(time.time()))
    body = b'{"type": "email.bounced", "email": "b@x.com"}'
    signed = f"msg_123.{ts}.".encode("utf-8") + body
    sig = base64.b64encode(
        hmac_mod.new(b"secret", signed, hashlib.sha256).digest()).decode()
    resp = client.post(
        "/api/email/webhook", content=body,
        headers={"Svix-Signature": f"v1,{sig}",
                 "webhook-id": "msg_123",
                 "webhook-timestamp": ts})
    assert resp.status_code == 200
    assert db_session.scalar(select(EmailEvent)).event_type == "bounced"


def test_webhook_rejects_replayed_stale_timestamp(monkeypatch, client):
    """A correctly-signed but replayed (old) webhook must be rejected — the
    freshness check closes the replay hole even when the HMAC validates."""
    import base64
    import hmac as hmac_mod
    import hashlib
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "secret")
    stale_ts = str(int(__import__("time").time()) - 3600 * 24)  # 1 day old
    body = b'{"type": "email.bounced", "email": "b@x.com"}'
    signed = f"msg_old.{stale_ts}.".encode("utf-8") + body
    sig = base64.b64encode(
        hmac_mod.new(b"secret", signed, hashlib.sha256).digest()).decode()
    resp = client.post(
        "/api/email/webhook", content=body,
        headers={"Svix-Signature": f"v1,{sig}",
                 "webhook-id": "msg_old",
                 "webhook-timestamp": stale_ts})
    assert resp.status_code == 401


def test_webhook_rejects_future_timestamp(monkeypatch, client):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "secret")
    future_ts = str(int(__import__("time").time()) + 3600 * 24)
    body = b'{"type": "email.bounced", "email": "b@x.com"}'
    resp = client.post(
        "/api/email/webhook", content=body,
        headers={"Svix-Signature": "v1,c2ln", "webhook-id": "msg_x",
                 "webhook-timestamp": future_ts})
    assert resp.status_code == 401


# --- unsubscribe ---------------------------------------------------------------
def test_unsubscribe_requires_valid_token(db_session, client):
    resp = client.get("/api/email/unsubscribe", params={"token": "garbage"})
    assert resp.status_code == 400


def test_unsubscribe_flips_preference(db_session, client):
    user = UserRepo(db_session).create("u@example.com", "hash")
    row = _seed_digest_pref(db_session, user, frequency="weekly")
    token = hmac_sign(str(row.id))
    resp = client.get("/api/email/unsubscribe", params={"token": token})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsubscribed"
    pref = db_session.get(DigestPreference, row.id)
    assert pref.frequency == "never"
    event = db_session.scalar(select(EmailEvent))
    assert event.event_type == "unsubscribed"


def test_unsubscribe_expired_token(db_session, client):
    user = UserRepo(db_session).create("u@example.com", "hash")
    row = _seed_digest_pref(db_session, user)
    token = hmac_sign(str(row.id), ttl_seconds=-10)
    resp = client.get("/api/email/unsubscribe", params={"token": token})
    assert resp.status_code == 400


# --- preview-digest ------------------------------------------------------------
def test_preview_digest_requires_auth(client):
    resp = client.post("/api/email/preview-digest")
    assert resp.status_code == 401


def test_preview_digest_returns_rendered_html(db_session, client):
    _seed_opportunity(db_session)
    auth = _register_and_login(client, "preview@example.com")
    resp = client.post("/api/email/preview-digest", headers=auth)
    assert resp.status_code == 404  # no profile yet — no digest to preview


def test_preview_digest_with_profile(db_session, client):
    _seed_opportunity(db_session)
    client.post("/api/auth/register",
                json={"email": "preview@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "preview@example.com",
                             "password": PASSWORD})
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = UserRepo(db_session).get_by_email("preview@example.com")
    _seed_digest_pref(db_session, user)
    resp = client.post("/api/email/preview-digest", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "weekly career digest" in body["subject"]
    assert "interstellar medium" in body["html"]