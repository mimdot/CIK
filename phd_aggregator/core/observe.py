"""core.observe — observability helpers (Sprint 10, B3).

Small, dependency-free: a request-id context that flows through the whole
request, a JSON log formatter, and a one-shot logger config used by the API.
Kept out of ``api.app`` so the CLI / worker can reuse it without pulling in
FastAPI. JSON logging is opt-in via ``CIK_JSON_LOGS=1`` (default off keeps the
human-friendly dev output); the admin wants it on in production so logs can be
ingested by a log platform.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Current request id (set by the API middleware; "-" when not inside a request).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Lazily install the JSON handler so ``configure_json_logging`` is idempotent.
_logger_configured = False


def set_request_id(value: str) -> None:
    """Bind a request id for the rest of this thread/async context."""
    request_id_var.set(value)


def get_request_id() -> str:
    return request_id_var.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request_id and
    any extra fields (e.g. ``status_code`` from the access log)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created,
                                           timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc_info"] = self.formatException(record.exc_info)
        # Structured extra fields (logging.debug(msg, extra={...})).
        for key in ("request_id", "method", "path", "status_code",
                    "duration_ms", "elapsed_ms", "feature", "source",
                    "event", "user_id"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if "request_id" not in entry:
            entry["request_id"] = get_request_id()
        return json.dumps(entry, ensure_ascii=True, default=str)


def configure_json_logging(level: int = logging.INFO,
                           logger_names: Optional[list[str]] = None,
                           flush_streams: bool = True) -> None:
    """Reconfigure a set of loggers to emit one-line JSON to stdout.

    ``logger_names`` defaults to the app's loggers (``phd_aggregator``,
    ``uvicorn``, ``uvicorn.error``, ``uvicorn.access``, ``rq.worker``).
    Idempotent per process. Uses the stdlib ``StreamHandler``; unterminated
    JSON lines are avoided with an explicit terminator.
    """
    global _logger_configured
    if _logger_configured:
        return
    targets = logger_names or ["phd_aggregator", "uvicorn", "uvicorn.error",
                              "uvicorn.general", "uvicorn.access",
                              "rq.worker"]
    for name in targets:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.terminator = "\n"
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    _logger_configured = True