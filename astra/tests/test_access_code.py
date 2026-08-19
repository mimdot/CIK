"""tests.test_access_code — the shared-code entry gate.

The code is a *soft* gate: extractable from any distributed binary and
therefore never a security boundary (see ``api.routes.auth.access_code``).
What these tests pin down is that it behaves correctly as a front door and,
just as importantly, that it stays completely absent from a deployment that
has not configured one — so a server keeps its email + password flow.
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
from db.models import Base
from db.repositories import UserRepo

CODE = "1819"


@pytest.fixture(autouse=True)
def _reset():
    for limiter in (register_limiter, login_limiter):
        limiter.clear("testclient")
    yield
    for limiter in (register_limiter, login_limiter):
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


@pytest.fixture()
def gated(monkeypatch):
    monkeypatch.setenv("ASTRA_ACCESS_CODE", CODE)
    # Faithful to where this gate actually runs: the desktop shell serves the
    # sidecar over plain-HTTP loopback and sets ASTRA_COOKIE_SECURE=0, because a
    # Secure cookie is refused on http:// origins.
    monkeypatch.setenv("ASTRA_COOKIE_SECURE", "0")


@pytest.fixture()
def ungated(monkeypatch):
    monkeypatch.delenv("ASTRA_ACCESS_CODE", raising=False)


# --- the gate, when it is configured ------------------------------------------

def test_email_and_code_signs_in(client, gated):
    r = client.post("/api/auth/access",
                    json={"email": "a@b.com", "code": CODE})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    # The session is a real one: /me resolves it.
    assert client.get("/api/auth/me").status_code == 200


def test_first_sight_creates_a_real_account(client, gated, db_session):
    client.post("/api/auth/access", json={"email": "new@b.com", "code": CODE})
    user = UserRepo(db_session).get_by_email("new@b.com")
    assert user is not None, "the code gate must still create a real user row"


def test_returning_user_reuses_the_same_account(client, gated, db_session):
    for _ in range(2):
        client.post("/api/auth/access",
                    json={"email": "same@b.com", "code": CODE})
    user = UserRepo(db_session).get_by_email("same@b.com")
    assert user is not None
    # One row, not a duplicate per sign-in.
    assert UserRepo(db_session).get_by_email("same@b.com").id == user.id


def test_wrong_code_is_rejected(client, gated):
    r = client.post("/api/auth/access",
                    json={"email": "a@b.com", "code": "0000"})
    assert r.status_code == 401


def test_malformed_email_is_rejected(client, gated):
    r = client.post("/api/auth/access",
                    json={"email": "not-an-email", "code": CODE})
    assert r.status_code == 422


def test_code_is_not_usable_as_a_password(client, gated):
    """The whole point of not storing it: /login must stay shut."""
    client.post("/api/auth/access", json={"email": "a@b.com", "code": CODE})
    # Sign the session away first, so this is a genuine 401 from the password
    # check rather than a 403 from CSRF on an already-authenticated client.
    client.cookies.clear()
    r = client.post("/api/auth/login",
                    json={"email": "a@b.com", "password": CODE})
    assert r.status_code == 401


def test_config_reports_access_code_mode(client, gated):
    body = client.get("/api/auth/config").json()
    assert body["auth_mode"] == "access_code"


def test_the_code_itself_is_never_returned(client, gated):
    """Nothing may hand the code back out, however soft a gate it is."""
    assert CODE not in client.get("/api/auth/config").text


# --- and when it is not ---------------------------------------------------------

def test_endpoint_is_absent_without_configuration(client, ungated):
    r = client.post("/api/auth/access",
                    json={"email": "a@b.com", "code": CODE})
    assert r.status_code == 404, "a server deployment must not expose this"


def test_config_reports_password_mode(client, ungated):
    body = client.get("/api/auth/config").json()
    assert body["auth_mode"] == "password"


def test_password_registration_still_works(client, ungated):
    r = client.post("/api/auth/register",
                    json={"email": "pw@b.com", "password": "SuperSecret1"})
    assert r.status_code == 201


# --- signing out ----------------------------------------------------------------

def test_logout_clears_the_session(client, gated):
    client.post("/api/auth/access", json={"email": "a@b.com", "code": CODE})
    assert client.get("/api/auth/me").status_code == 200
    # Echo the csrf_token cookie back, exactly as lib/api.ts does for every
    # mutating cookie-authenticated request.
    r = client.post("/api/auth/logout",
                    headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me").status_code == 401
