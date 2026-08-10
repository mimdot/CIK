"""core.email — transactional email delivery via Resend (Sprint 07, Track A1).

Provider-agnostic wrapper: when ``RESEND_API_KEY`` is set we POST rendered
messages to the Resend API over httpx (async-capable, already a dependency).
Without a key the module *logs* the message instead of sending — dev mode that
keeps the whole test suite offline and deterministic.

Senders must never block the request path: the API always dispatches sends
through the job queue (see ``core.tasks.send_digest_job``), never inline.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("phd_aggregator")

DEFAULT_FROM = os.environ.get(
    "EMAIL_FROM", "Career Intelligence <no-reply@example.com>")

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = httpx.Timeout(15.0)


def resend_api_key() -> str:
    """The configured Resend API key (empty string in dev mode)."""
    return os.environ.get("RESEND_API_KEY", "").strip()


def is_email_configured() -> bool:
    """True when a real email backend is configured (a send will go out)."""
    return bool(resend_api_key())


def _redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def send_email(to: str, subject: str, html: str,
               text: Optional[str] = None,
               from_email: Optional[str] = None) -> dict:
    """Send one transactional email via Resend.

    Returns ``{"status": "sent", "id": ...}`` when delivered,
    ``{"status": "skipped", "id": None}`` in dev mode (no API key), and
    ``{"status": "failed", "id": None}`` on a Resend error — **never raises**
    so callers (background jobs) always get a value to record.

    ``from_email`` overrides the environment default for a single send (used by
    tests to avoid depending on ``EMAIL_FROM``).
    """
    api_key = resend_api_key()
    sender = from_email or DEFAULT_FROM
    to = (to or "").strip()
    if not to:
        log.warning("send_email called without a recipient — skipping")
        return {"status": "skipped", "id": None}

    if not api_key:
        log.info("RESEND_API_KEY unset — dev mode, skipping email to %s "
                 "(subject=%r)", to, subject)
        return {"status": "skipped", "id": None}

    payload: dict = {"from": sender, "to": [to], "subject": subject,
                     "html": html}
    if text:
        payload["text"] = text

    try:
        resp = httpx.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:  # network / timeout — never raises to caller
        log.warning("email.send failed (%s) to %s: %s", type(exc).__name__,
                    to, exc)
        return {"status": "failed", "id": None}

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        email_id = data.get("id")
        log.info("email.sent to=%s subject=%r id=%s", to, subject, email_id)
        return {"status": "sent", "id": email_id}

    log.warning("email.send rejected (HTTP %s) to=%s: %s",
                resp.status_code, to, resp.text[:500])
    return {"status": "failed", "id": None}