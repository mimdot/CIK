"""tests.test_csrf — Sprint 07, Track B3.

Verifies the double-submit-cookie CSRF protection:
- cookie-authenticated mutations without X-CSRF-Token are rejected (403)
- cookie + matching header succeeds
- Bearer-authenticated requests bypass the check
- public endpoints (register/login/forgot-password) and the webhook are exempt
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from api.security import login_limiter, register_limiter, reset_limiter
from db.models import Base, UserProfileRow
from db.repositories import UserRepo

PASSWORD = "SuperSecret1"


@pytest.fixture(autouse=True)
def _reset():
    for limiter in (register_limiter, login_limiter, reset_limiter):
        limiter.clear("testclient")
    yield
    for limiter in (register_limiter, login_limiter, reset_limiter):
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


def _login(client):
    client.post("/api/auth/register",
                json={"email": "csrf@example.com", "password": PASSWORD})
    resp = client.post("/api/auth/login",
                       json={"email": "csrf@example.com",
                             "password": PASSWORD})
    assert resp.status_code == 200
    return resp


def _seed_profile(db_session, user_id: int) -> None:
    db_session.add(UserProfileRow(user_id=user_id, domain="astronomy",
                                  subfield="interstellar medium",
                                  confidence=0.9, active=True))
    db_session.commit()


def _login_with_profile(client, db_session):
    """Log in and seed a profile so /api/preferences can succeed. TestClient
    does not resend ``Secure`` cookies over http, so the session + csrf cookies
    are re-created explicitly to simulate a real browser."""
    resp = _login(client)
    user = UserRepo(db_session).get_by_email("csrf@example.com")
    _seed_profile(db_session, user.id)
    token = resp.json()["access_token"]
    csrf = client.cookies.get("csrf_token")
    client.cookies.delete("cik_token")
    client.cookies.delete("csrf_token")
    client.cookies.set("cik_token", token)
    client.cookies.set("csrf_token", csrf)
    return {"token": token, "csrf": csrf}


def test_login_sets_csrf_cookie(client):
    resp = _login(client)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "csrf_token=" in set_cookie
    # The csrf cookie must be readable by JS (non-httpOnly).
    csrf_part = set_cookie.split("csrf_token=")[1]
    csrf_part = csrf_part.split(", ")[0]
    assert "HttpOnly" not in csrf_part
    assert "SameSite=strict" in csrf_part


def test_cookie_auth_mutation_without_header_rejected(client, db_session):
    _login_with_profile(client, db_session)
    # Session cookie present, no X-CSRF-Token header -> blocked by middleware.
    resp = client.post("/api/preferences",
                       json={"digest_enabled": True})
    assert resp.status_code == 403


def test_cookie_auth_mutation_with_header_passes_middleware(client,
                                                            db_session):
    ctx = _login_with_profile(client, db_session)
    resp = client.post("/api/preferences",
                       json={"digest_enabled": True},
                       headers={"X-CSRF-Token": ctx["csrf"]})
    # Cookie auth is real now: a valid double-submit passes the middleware AND
    # the endpoint authenticates the user from the session cookie (200).
    assert resp.status_code == 200
    assert resp.json()["digest_enabled"] is True


def test_cookie_auth_get_round_trip(client, db_session):
    """A browser session restored from the httpOnly cookie authenticates GETs."""
    _login_with_profile(client, db_session)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "csrf@example.com"


def test_invalid_bearer_does_not_fall_back_to_cookie(client, db_session):
    """A present-but-invalid Bearer must 401 rather than silently using the
    cookie session (otherwise CSRF exemptions for Bearer clients would leak
    onto cookie-authenticated requests)."""
    _login_with_profile(client, db_session)
    resp = client.get("/api/auth/me",
                      headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_mismatched_header_rejected(client, db_session):
    _login_with_profile(client, db_session)
    resp = client.post("/api/preferences",
                       json={"digest_enabled": True},
                       headers={"X-CSRF-Token": "wrong-value"})
    assert resp.status_code == 403


def test_bearer_auth_bypasses_csrf(client, db_session):
    ctx = _login_with_profile(client, db_session)
    resp = client.post("/api/preferences",
                       json={"digest_enabled": True},
                       headers={"Authorization": f"Bearer {ctx['token']}"})
    assert resp.status_code == 200


def test_public_endpoints_exempt(client):
    resp = client.post("/api/auth/forgot-password",
                       json={"email": "nobody@example.com"})
    assert resp.status_code == 200


def test_webhook_exempt_from_csrf(client):
    resp = client.post("/api/email/webhook",
                       json={"type": "email.bounced", "email": "b@x.com"})
    assert resp.status_code == 200



# --- the desktop lock-out ----------------------------------------------------

def test_sign_in_is_not_blocked_by_a_stale_session_cookie(client):
    """A stale cik_token must never block establishing a new session.

    The desktop shell issues a fresh ASTRA_SECRET_KEY on every launch, so the
    previous run's cik_token cookie is invalid but still sent, while its
    csrf_token counterpart has expired. CSRF then rejected every sign-in with
    403 and the user was locked out for good -- unable to clear the cookie from
    a page they could never load.
    """
    resp = client.post("/api/auth/login",
                       json={"email": "nobody@example.com", "password": "x"},
                       cookies={"cik_token": "stale-from-a-previous-launch"})
    # Anything but the CSRF rejection: wrong credentials are fine, being told
    # "CSRF token missing or invalid" is not.
    assert resp.status_code != 403, resp.text
    assert "CSRF" not in resp.text


def test_a_csrf_rejection_still_carries_cors_headers(client):
    """A short-circuited response must not look like an unreachable server.

    CORSMiddleware has to be OUTERMOST. When it sat inside CsrfMiddleware, a
    403 came back with no Access-Control-Allow-Origin, so the browser blocked
    the response instead of surfacing the status and fetch() rejected -- which
    the frontend can only report as "Cannot reach the API server". The real
    reason was invisible in the UI and in the network panel alike.
    """
    origin = "tauri://localhost"
    resp = client.post("/api/account/delete",
                       json={},
                       headers={"Origin": origin},
                       cookies={"cik_token": "stale"})
    assert resp.status_code == 403
    assert "CSRF" in resp.text
    assert resp.headers.get("access-control-allow-origin") is not None, (
        "a CSRF 403 with no CORS headers reads as a network failure in the "
        "browser, not as a 403")
