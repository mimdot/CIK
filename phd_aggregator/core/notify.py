"""core.notify — operations alert channel (Sprint 09, Track B1/B4/C2).

A single best-effort alert path used by the source-health drift detector, the
API-anomaly detector, and (Sprint 10) the launch monitoring stack: deliver a
message to Sentry + an ops webhook (``OPS_WEBHOOK_URL``, e.g. Slack/Telegram/
Discord), and degrade to a log line when neither is configured. Never raises —
alerting must not take the caller down.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("phd_aggregator")


def _sentry_available() -> bool:
    try:
        import sentry_sdk  # noqa: F401
        return bool(os.environ.get("SENTRY_DSN", "").strip())
    except Exception:
        return False


def notify_ops(message: str, tags: Optional[list] = None) -> str:
    """Send an ops alert; returns the channel name that handled it.

    Prioritises Sentry, then ``OPS_WEBHOOK_URL``, then the log. ``tags`` are
    short identifiers (e.g. ``UnhandledError``, ``SourceDrift``) that Sentry
    tags with so alert rules can fire on them. Every failure is logged, never
    raised.
    """
    message = str(message)
    tags = [str(t) for t in (tags or [])][:5]

    if _sentry_available():
        try:
            import sentry_sdk
            sentry_sdk.capture_message(message, level="warning")
            if tags:
                sentry_sdk.set_tag("alert", tags[0])
            return "sentry"
        except Exception as exc:
            log.warning("Sentry alert failed: %s", exc)
            _sentry_available.__self__  # noqa: B018 - keep import-local

    webhook = os.environ.get("OPS_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            import httpx
            payload = {"text": message}
            if tags:
                payload["tags"] = tags
            httpx.post(webhook, json=payload, timeout=5.0)
            return "webhook"
        except Exception as exc:
            log.warning("ops webhook alert failed (%s) — falling back to log",
                        exc)

    log.warning("OPS ALERT [%s]: %s", ",".join(tags) or "ops", message)
    return "log"