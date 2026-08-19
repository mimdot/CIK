"""tests.test_observe — Sprint 10, B3 observability.

The RequestIdMiddleware tags every request, echoes ``X-Request-Id`` back, and
records a structured access log. The JSON formatter emits one parseable object
per line with the request id attached.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app import app
from api.deps import get_db
from core import observe


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    from db.models import Base
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


def test_request_id_echoed(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    rid = resp.headers.get("x-request-id")
    assert rid and len(rid) >= 8


def test_callers_request_id_preserved(client):
    resp = client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert resp.headers.get("x-request-id") == "abc-123"


def test_request_id_context_default_is_dash():
    # Outside a request the context keeps its neutral default.
    _tok = observe.request_id_var.set("stale")
    observe.request_id_var.reset(_tok)
    assert observe.get_request_id() == "-"


def test_json_formatter_is_valid_json():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(observe.JsonFormatter())
    logger = logging.getLogger("observe.test.logger")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    observe.set_request_id("rid-99")
    logger.info("hello %s", "world")
    entry = json.loads(buf.getvalue().strip())
    assert entry["message"] == "hello world"
    assert entry["request_id"] == "rid-99"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "observe.test.logger"


def test_json_formatter_non_native_types_do_not_crash():
    import datetime as _dt
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(observe.JsonFormatter())
    logger = logging.getLogger("observe.test.types")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("ts", extra={"elapsed_ms": _dt.timedelta(seconds=1)})
    entry = json.loads(buf.getvalue().strip())
    assert "elapsed_ms" in entry  # converted via default=str