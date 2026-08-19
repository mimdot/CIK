"""tests.test_email — Sprint 07, Track A1.

Tests core.email.send_email in all three modes: dev-mode skip (no key),
successful Resend delivery (httpx mocked), and failed delivery (httpx mocked
to a 500). No real network and no real API key required.
"""

from __future__ import annotations

import pytest

from core import email


@pytest.fixture(autouse=True)
def _no_resend_key(monkeypatch):
    """Default to dev mode (no key) unless a test overrides it."""
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("EMAIL_FROM", "Astra <noreply@example.com>")


def test_dev_mode_skips_when_no_key():
    """Without RESEND_API_KEY the send is skipped (logged), not raised."""
    result = email.send_email("user@example.com", "Hello", "<p>Hi</p>")
    assert result == {"status": "skipped", "id": None}


def test_empty_recipient_skipped(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_X")
    result = email.send_email("  ", "Hello", "<p>Hi</p>")
    assert result == {"status": "skipped", "id": None}


def test_success_sends_via_httpx(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_abc123")
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": "email_123"}

    def fake_post(url, **kwargs):
        assert url == email._RESEND_URL
        assert kwargs["headers"]["Authorization"] == "Bearer re_abc123"
        captured["payload"] = kwargs["json"]
        return _Resp()

    monkeypatch.setattr(email.httpx, "post", fake_post)

    result = email.send_email("a@b.com", "Topic", "<b>x</b>", text="x")
    assert result == {"status": "sent", "id": "email_123"}
    assert "@" in captured["payload"]["from"] and ">" in captured["payload"]["from"]
    assert captured["payload"]["to"] == ["a@b.com"]
    assert captured["payload"]["subject"] == "Topic"
    assert captured["payload"]["html"] == "<b>x</b>"
    assert captured["payload"]["text"] == "x"


def test_http_error_returns_failed(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_abc123")

    class FakeResp:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(email.httpx, "post", lambda *a, **k: FakeResp())

    result = email.send_email("a@b.com", "Topic", "<p>x</p>")
    assert result == {"status": "failed", "id": None}


def test_network_exception_returns_failed(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_abc123")

    def boom(*a, **k):
        raise email.httpx.ConnectError("no network")

    monkeypatch.setattr(email.httpx, "post", boom)

    result = email.send_email("a@b.com", "Topic", "<p>x</p>")
    assert result == {"status": "failed", "id": None}


def test_is_email_configured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert email.is_email_configured() is False
    monkeypatch.setenv("RESEND_API_KEY", "   ")
    assert email.is_email_configured() is False
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    assert email.is_email_configured() is True