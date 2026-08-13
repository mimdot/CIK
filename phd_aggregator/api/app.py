"""api.app — the FastAPI application (Sprint 04, A1 + Sprint 05, B3/B4 +
Sprint 06, B3 Sentry).

Wires configurable CORS + security headers + liveness/readiness probes and
mounts every resource router. Start with:
    uvicorn api.app:app --reload
from the ``phd_aggregator/`` directory; OpenAPI docs live at ``/docs``.

Production knobs (env vars, see ``.env.example``):
- ``CORS_ORIGINS`` — comma-separated allowed origins; when unset the API uses
  the permissive dev default (any origin, no credentials).
- ``SENTRY_DSN`` — when set, initializes Sentry error tracking with a 10%
  trace sample rate and per-request user context.
"""

from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

import hmac
import sentry_sdk
from core.env import env_flag
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.deps import _get_engine
from api.metrics import metrics
from core import observe
from api.routes import (account, admin, apikeys, assistant, auth, bookmarks,
                        email as email_router, invites, matches,
                        opportunities, pipeline, preferences, profile,
                        supervisors)
from api.routes.pipeline import jobs_router
from api.routes.v1 import router as v1_router
from core.config import FIELD_PROFILE, list_field_profiles

# --- Sentry (Sprint 06, B3) ---------------------------------------------------
_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        release=f"career-intelligence-kit@{os.environ.get('CIK_VERSION', 'dev')}",
        traces_sample_rate=0.1,  # 10% of requests
        send_default_pii=False,
    )


def _set_sentry_user(request: Request) -> None:
    """Attach the authenticated user's id/email to Sentry events."""
    if not sentry_sdk.get_client().is_active():
        return
    token = request.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        from api.security import decode_access_token
        user_id = decode_access_token(token[len("Bearer "):])
        if user_id is not None:
            sentry_sdk.set_user({"id": str(user_id)})


# --- weekly digest scheduler (Sprint 07, A3) — started via lifespan -----------
# Start the in-process fallback scheduler once per process. With Redis +
# rq-scheduler present this registers a cron instead (see core.tasks). Disabled
# under tests (CIK_TESTING=1) so the test suite spawns no background threads.
_started_scheduler = False


def _start_scheduler() -> None:
    global _started_scheduler
    # Disable in every process except one (e.g. `CIK_SCHEDULER_ENABLED=0` on
    # extra uvicorn workers) so the weekly-digest cron is never registered
    # more than once per deployment. Disabled under tests too (CIK_TESTING=1).
    if not env_flag("CIK_SCHEDULER_ENABLED", default=True):
        return
    if _started_scheduler or os.environ.get("CIK_TESTING", "") == "1":
        return
    _started_scheduler = True
    try:
        from core.tasks import start_digest_scheduler
        start_digest_scheduler()
    except Exception:  # pragma: no cover - infra dependent
        logging.getLogger("phd_aggregator").exception(
            "digest scheduler failed to start")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Process startup/shutdown (replaces the deprecated on_event('startup'))."""
    _start_scheduler()
    yield


app = FastAPI(title="Career Intelligence API", version="0.1.0",
              lifespan=lifespan,
              description="REST API over the PhD aggregator's profiles, "
                          "opportunities, matches, supervisors and pipeline. "
                          "Public, versioned developer API under /api/v1 "
                          "authenticates with scoped Bearer API keys "
                          "(60 req/min, optional daily quota); see "
                          "docs/DEVELOPER_API.md for the stable contract. "
                          "The unversioned routes are internal (dashboard) "
                          "and may change.",
              servers=[{"url": "/", "description": "Same origin as docs"}])

# --- CORS --------------------------------------------------------------------
# CORS_ORIGINS is a comma-separated allow-list. When set we enable credentials
# (the httpOnly auth cookie) for exactly those origins; unset = dev default.
_cors_env = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_env:
    _origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # dev default; tighten via CORS_ORIGINS
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --- request metrics (Sprint 06, C4) ------------------------------------------
class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count / latency / 5xx errors for the admin dashboard."""

    async def dispatch(self, request: Request, call_next):
        import time
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        metrics.record(response.status_code, elapsed)
        from core import anomaly
        anomaly.submit(response.status_code, elapsed)
        return response


# --- request id + access log (Sprint 10, B3) -----------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    """Tag every request with a short request id.

    Ids come from the caller's ``X-Request-Id`` header when present (useful to
    correlate with the dashboard's fetch), otherwise a fresh random id. The id
    is echoed back in the ``X-Request-Id`` response header and bound to the
    thread-local context so log lines within the request carry it. Emits a
    single structured access-log line per call.
    """

    async def dispatch(self, request: Request, call_next):
        import logging
        import time
        import uuid
        request_id = request.headers.get("x-request-id", "") or uuid.uuid4().hex[:12]
        observe.set_request_id(request_id)
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logging.getLogger("phd_aggregator").info(
            "http %s %s -> %s (%.1f ms)",
            request.method, request.url.path, response.status_code, duration_ms,
            extra={"request_id": request_id, "method": request.method,
                   "path": request.url.path,
                   "status_code": response.status_code,
                   "duration_ms": duration_ms})
        response.headers["X-Request-Id"] = request_id
        return response


# --- security headers ----------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add hardening headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = \
            "max-age=31536000; includeSubDomains"
        return response


# --- CSRF protection (Sprint 07, B3) -------------------------------------------
class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF check for cookie-authenticated mutations.

    The API authenticates browsers via the httpOnly ``cik_token`` cookie, which
    makes ``POST`` endpoints vulnerable to cross-site request forgery. This
    middleware requires mutating requests that use cookie auth to echo the
    ``csrf_token`` cookie in the ``X-CSRF-Token`` header (both were set by
    ``POST /api/auth/login``).

    Exempt: safe methods (GET/HEAD/OPTIONS), Bearer-token authenticated clients
    (API consumers / native apps), the Resend webhook (signature-authenticated),
    and requests with no session cookie at all (nothing to protect).
    """

    _MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next):
        if request.method in self._MUTATING:
            if request.url.path == "/api/email/webhook":
                pass
            elif request.headers.get("Authorization", "").startswith("Bearer "):
                pass
            elif "cik_token" in request.cookies:
                header = request.headers.get("x-csrf-token", "")
                cookie = request.cookies.get("csrf_token", "")
                if not header or not cookie or not hmac.compare_digest(
                        header, cookie):
                    return Response(status_code=403,
                                    content='{"detail": "CSRF token missing '
                                            'or invalid"}',
                                    media_type="application/json")
        return await call_next(request)


app.add_middleware(CsrfMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIdMiddleware)  # outermost: captures the full request

# JSON structured logs (Sprint 10, B3) — on in production, off in dev/tests.
if env_flag("CIK_JSON_LOGS", default=False):
    observe.configure_json_logging()

# Warn if running in dev cookie mode (no Secure flag) — production deployments
# must serve cookies over HTTPS to prevent session hijacking.
if not env_flag("CIK_COOKIE_SECURE", default=True):
    logging.getLogger("phd_aggregator").warning(
        "CIK_COOKIE_SECURE=0 — session cookies lack the Secure flag. "
        "This is expected for local HTTP development but unsafe behind HTTPS. "
        "Ensure CIK_COOKIE_SECURE=1 in production."
    )


# --- meta endpoints ------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe used by the dashboard and load balancers."""
    return {"status": "ok", "version": app.version}


@app.get("/ready", tags=["meta"])
def ready() -> dict:
    """Readiness probe: 200 when the DB is reachable, 503 otherwise.

    ``llm`` reports whether an LLM provider credential is present so operators
    can see (but not be blocked by) LLM availability."""
    try:
        engine = _get_engine()
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - depends on infra
        raise HTTPException(status_code=503, detail=f"DB not ready: {exc}")
    return {"status": "ready", "db": "ok", "llm": _llm_configured()}


def _llm_configured() -> bool:
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY",
                "GROQ_API_KEY", "GEMINI_API_KEY",
                "LLM_API_KEY", "OLLAMA_HOST"):
        if os.environ.get(key):
            return True
    return False


@app.get("/api/fields", tags=["meta"])
def list_fields() -> dict:
    """Public list of available field profiles (for the settings dropdown)."""
    return {"default": FIELD_PROFILE, "profiles": sorted(list_field_profiles())}


# --- /api/v1 error envelope (Sprint 08, Track B3) ------------------------------
# Public API errors follow a fixed shape: {"error": {"code", "message",
# "detail"?}}. Internal routes keep FastAPI's default {"detail": ...} shape —
# the dashboard and CLI already parse that, so only /api/v1/* is affected.
def _is_v1(path: str) -> bool:
    return path.startswith("/api/v1/")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if not _is_v1(request.url.path):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail},
                            headers=exc.headers)
    body = {"error": {"code": "http_error", "message": exc.detail}}
    if exc.headers:
        body["error"]["detail"] = exc.headers
    return JSONResponse(status_code=exc.status_code, content=body,
                        headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    if not _is_v1(request.url.path):
        return JSONResponse(status_code=422,
                            content={"detail": jsonable_encoder(exc.errors())})
    return JSONResponse(status_code=422, content={
        "error": {"code": "validation_error", "message": "Request validation "
                                                        "failed",
                  "detail": jsonable_encoder(exc.errors())}})


app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(opportunities.router)
app.include_router(matches.router)
app.include_router(supervisors.router)
app.include_router(bookmarks.router)
app.include_router(preferences.router)
app.include_router(pipeline.router)
app.include_router(jobs_router)
app.include_router(invites.router)
app.include_router(admin.router)
app.include_router(email_router.router)
app.include_router(apikeys.router)
app.include_router(assistant.router)
app.include_router(account.router)
app.include_router(v1_router)
