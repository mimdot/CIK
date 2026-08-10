# Sprint 07: Email Service + Auth Hardening

**Duration:** Weeks 1-2 (target: 2026-08-18 → 2026-08-31)
**Goal:** Build the missing email delivery service (weekly digest via Resend), harden auth (Redis-backed rate limiting, password reset, email verification, CSRF, audit log), and turn the CLI self-test into a scriptable CI/deploy gate.

---

## What shipped in Sprints 01-06 (for context)

| Item | Status |
|------|--------|
| Full backend (CLI + FastAPI 18+ endpoints + matching + profile + DB) | DONE |
| Dashboard (8 pages, responsive, auth-gated) | DONE |
| Docker + compose (API, dashboard, worker, optional PG/Redis) | DONE |
| Security baseline (JWT, bcrypt, in-memory rate limiting, CORS, headers) | DONE |
| Private beta (invites, onboarding, feedback, admin monitoring) | DONE |
| Tests: 452 passing | DONE |

**Critical gap being closed in this sprint:** the weekly email digest is a
*feature of the product promise* (`prompts/05_OpenCode_Email_Service.md`) but
today it is only a database toggle (`DigestPreference` in `db/models.py:272`)
— there is **no code that sends an email**. This sprint ships that code.

---

## Track A: Email Service (Resend)

### A1: Email client — `core/email.py`
**Effort:** 1 day
**Deliverable:** `core/email.py` + `tests/test_email.py`

```python
# core/email.py
# Provider-agnostic send wrapper. Uses Resend when RESEND_API_KEY is set,
# else logs the rendered message to the logger (dev mode) — never crashes a run.
import os, logging
from typing import Optional

log = logging.getLogger("phd_aggregator")

DEFAULT_FROM = os.environ.get("EMAIL_FROM", "Career Intelligence <no-reply@example.com>")

def send_email(to: str, subject: str, html: str,
               text: Optional[str] = None) -> dict:
    """Send one transactional email via Resend (async). Returns {id, status}."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        log.info("RESEND_API_KEY unset — skipping send to %s (subject=%r)", to, subject)
        return {"status": "skipped", "id": None}
    # Use `resend` PyPI package or raw httpx POST to https://api.resend.com/emails
    ...
```

Requirements:
- Wrap Resend REST API (`POST https://api.resend.com/emails` with
  `Authorization: Bearer <key>`), using `httpx` (already a dependency).
- **Dev mode**: no key → log the rendered email instead of sending (keeps the
  test suite offline).
- **Bounce tracking**: expose a `POST /api/email/webhook` (see A4) that Resend
  calls on `email.bounced` / `email.complained` events; store the event in a
  new `email_events` table.
- Timeouts + retry (2 retries, backoff) — email must never block the request
  path; call senders asynchronously via the job queue (Track B).

### A2: Digest builder — `core/digest.py`
**Effort:** 1 day
**Deliverable:** `core/digest.py` + `tests/test_digest.py`

Build the weekly digest from a profile's existing scored matches. Follows the
`prompts/05` contract exactly:

- Only opportunities with `match_score > 0.85`
- Maximum 5 positions
- Maximum 5 supervisors (when `DigestPreference.include_supervisors` is on)
- Each item includes: **why matched** (the `match_explanation`), **deadline**,
  **funding**, **next action**

```python
def build_digest(profile: UserProfile, top_positions: list[dict],
                 top_supervisors: list[dict] = None) -> dict:
    """Return a rendered {subject, html, text} digest from pre-scored matches.

    Sorting/selection is DETERMINISTIC (score desc, then deadline asc). No LLM
    in this sprint — LLM personalization arrives in Sprint 09.
    """
```

- HTML template (inline-styled table — most email clients strip `<style>`);
  every item links back to the dashboard.
- Unsubscribe: each email includes a signed one-click `unsubscribe_token`
  (HMAC over user id + secret) → `GET /api/email/unsubscribe?t=...` sets
  `DigestPreference.frequency='never'`.
- Deterministic and unit-testable with a plain `UserProfile` + match fixtures
  (mirrors how `matching/scorer.py` is tested).

### A3: Weekly scheduler — `core/tasks.py` addition
**Effort:** 0.5 days
**Deliverable:** `core/tasks.py` `enqueue_digest_job()` + `send_digest_job()`

```python
# core/tasks.py (addition)
def send_digest_job(profile_id: int) -> int:
    """Fetch the profile's top matches, build the digest, send via Resend.
    Returns the number of emails sent (0 when skipped). Never raises:
    failures are logged and recorded in email_events."""
```

- **Trigger:** `rq-scheduler` cron `0 8 * * 1` (Monday 08:00 UTC) iterating
  all `DigestPreference` rows where `frequency='weekly'`; each profile enqueues
  a `send_digest_job`.
- **Fallback** (no Redis): a `threading.Timer` daily check inside the API that
  fires missed weekly digests — mirrors the existing `_fallback_run` pattern in
  `core/tasks.py:64`.
- Add `rq-scheduler` to `requirements.txt`; document the cron in
  `docs/DEPLOYMENT.md`.

### A4: Email routes — `api/routes/email.py`
**Effort:** 0.5 days
**Deliverable:** `api/routes/email.py`, `tests/test_email_routes.py`

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/email/webhook` | POST | Resend signature header | Receive bounce/complaint events → `email_events` |
| `/api/email/unsubscribe` | GET | signed token | One-click unsubscribe (redirect to a "unsubscribed" page) |
| `/api/email/preview-digest` | POST | user | Render this week's digest as HTML for the Settings page preview (no send) |

- Register in `api/app.py`.
- Webhook must verify Resend's signature (shared `RESEND_WEBHOOK_SECRET`) to
  prevent spoofed bounces marking good addresses as failed.

### A5: Digest tests
**Effort:** 0.5 days

- Test: `build_digest` returns ≤5 positions, only `> 0.85` scores, correct sort.
- Test: subject/body contain the matched terms, deadlines, and next actions.
- Test: unsubscribe token round-trip (issue → verify → invalidate).
- Test: dev-mode skip when `RESEND_API_KEY` unset.
- Test: webhook rejects bad signatures; records valid events.

---

## Track B: Auth + Security Hardening

### B1: Redis-backed rate limiter — `api/security.py`
**Effort:** 1 day
**Deliverable:** refactor `api/security.py` + `core/ratelimit.py`

**Problem:** the current `_RateLimiter` (`api/security.py:32`) is
**in-memory and process-local** — with `uvicorn --workers 4` each worker has
its own counter, so limits are 4x permissive and reset on restart. Not
acceptable for a 1000-user launch.

```python
# core/ratelimit.py
class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis (shared across workers).
    Falls back to the existing in-memory _RateLimiter when Redis is absent."""
    def __init__(self, max_requests: int, window_seconds: int, prefix: str):
        ...
    def check(self, key: str) -> bool:
        # INCR + EXPIRE on a key like rate:{prefix}:{key}:{window_bucket}
    def remaining(self, key: str) -> int:
        ...
```

- Keep the public API of `api/security.py` unchanged (`register_limiter`,
  `login_limiter`, `check`/`remaining`) so callers (`api/routes/auth.py`) do
  not change — swap the internals to `RedisRateLimiter` with an in-memory
  fallback via the `core/cache._get_redis()` connection.
- Add per-user + per-IP keys (both checked) to blunt distributed brute-force.
- **Lockout**: after N failed logins for an email, require a cooldown (sliding
  window) — Redis makes this durable across workers.

### B2: Password reset + email verification
**Effort:** 1 day
**Deliverable:** `api/routes/auth.py` additions + `db/models.py` + tests

New tables:
```python
class PasswordReset(Base):
    __tablename__ = "password_resets"
    id, user_id (FK), token_hash (SHA-256, no plaintext), expires_at, used_at

class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id, user_id (FK), token_hash, expires_at, used_at
```

Endpoints (all public, rate-limited):
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/forgot-password` | POST | `{email}` → issue reset token, email a link (only if the address exists — no user enumeration) |
| `/api/auth/reset-password` | POST | `{token, new_password}` → verify + rotate password, invalidate token + all JWTs |
| `/api/auth/verify-email` | POST | `{token}` → mark email verified |
| `/api/auth/resend-verification` | POST | resend verification email (rate-limited) |

- Tokens: `secrets.token_urlsafe(32)`, stored **hashed** (SHA-256); 24 h expiry,
  single-use.
- Add `email_verified` boolean + `email_verified_at` to `User`.
- Registration: `POST /api/auth/register` now also issues a verification token
  and (optionally) emails it. Dev mode logs the link instead of sending.
- Guard: password reset emails and forgot-password responses must be identical
  whether or not the address exists (prevents account enumeration).

### B3: CSRF protection
**Effort:** 0.5 days
**Deliverable:** `api/security.py` + middleware in `api/app.py` + tests

- The API authenticates via an httpOnly cookie (`cik_token`) — that is CSRF
  attack surface. Add a **double-submit cookie** pattern:
  - `POST /api/auth/login` returns a `csrf_token` cookie (non-httpOnly, random).
  - Mutating requests (POST/PUT/DELETE) must echo the token in the
    `X-CSRF-Token` header; a middleware compares it to the cookie.
- Exempt: requests authenticated via `Authorization: Bearer` (API keys, native
  clients) and `/api/email/webhook` (signature-authenticated).
- `SameSite=Strict` (already set on the auth cookie) + CSRF header check gives
  defense-in-depth. The dashboard's `lib/api.ts` must attach the header on
  mutations.

### B4: Audit log — `db/models.py` + `api/routes/admin.py`
**Effort:** 0.5 days
**Deliverable:** `AuditEvent` model + `api/security.py` `log_audit()` + admin view

```python
class AuditEvent(Base):
    __tablename__ = "audit_events"
    id, actor_type (user|apikey|system), actor_id, action, target_type,
    target_id, ip, user_agent, meta (JSON), created_at
```

- Record: register, login success/fail, password reset, email verify,
  unsubscribe, invite create/redeem, admin actions, API-key create/revoke
  (Sprint 08).
- Admin endpoint `GET /api/admin/audit?action=&actor=&page=` (admin-only) +
  tab in the admin dashboard.

### B5: Security tests
**Effort:** 0.5 days

- Test rate limiter with a fake Redis + in-memory fallback (200/429 paths).
- Test forgot-password returns the same body whether or not the email exists.
- Test reset-token is single-use, expires, and rotates the password.
- Test CSRF: mutating request without header → 403; with cookie+header → ok;
  Bearer-authenticated requests bypass.
- Test audit rows are written for register/login/admin actions.

---

## Track C: Self-Test Automation

### C1: Scriptable self-test gate — `scripts/self_test.sh`
**Effort:** 0.5 days
**Deliverable:** `scripts/self_test.sh` (project root)

```bash
#!/usr/bin/env bash
# Self-test gate used by CI and deploy hooks (Sprint 07, Track C1).
# Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Offline CLI self-test =="
(cd phd_aggregator && python phd_aggregator.py --self-test)

echo "== 2. Backend unit/integration tests =="
(cd phd_aggregator && python -m pytest tests/ -q)

echo "== 3. Dashboard unit tests =="
(cd dashboard && npm test -- --runInBand)

echo "== 4. Live source sweep (best-effort, warn-only) =="
(cd phd_aggregator && python test_supervisors.py --whole-only) || \
  echo "WARN: live source sweep failed (network/anti-bot) — not fatal"

echo "SELF-TEST PASSED"
```

- `scripts/self_test_fast.sh` variant: steps 1-3 only (CI, no network).
- Wire into the repo's `README.md` and `docs/GETTING_STARTED.md`.

### C2: Deploy-time smoke test — `scripts/smoke_test.sh`
**Effort:** 0.5 days
**Deliverable:** `scripts/smoke_test.sh`

```bash
# After docker compose up: verify the stack is actually serving.
curl -fsS http://localhost:8000/health           # liveness
curl -fsS http://localhost:8000/ready            # DB reachable
curl -fsS -o /dev/null -w '%{http_code}' http://localhost:3000  # dashboard
# register a throwaway user, login, build profile, list matches, delete user
```

- Uses a `CIK_SMOKE_TEST=1` env flag so the throwaway account is cleaned up.
- Gate for the `deploy` step of CI/CD (Sprint 10).

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (Email client) | `core.email.send_email` works against a Resend test key; dev mode logs instead of sending |
| A2 (Digest builder) | `build_digest` returns ≤5 positions with score > 0.85, why/deadline/funding/next-action per item |
| A3 (Scheduler) | Weekly digest enqueued via rq-scheduler (and threading fallback); no email blocks a request |
| A4 (Email routes) | Webhook verifies signature; unsubscribe token round-trips |
| A5 (Digest tests) | All digest/email tests pass |
| B1 (Rate limiter) | Limits are shared across uvicorn workers when Redis is on; in-memory fallback still works |
| B2 (Password reset) | Forgot → email → reset → re-login works; tokens hashed, single-use, no enumeration |
| B3 (CSRF) | Mutating cookie-auth requests require `X-CSRF-Token`; Bearer bypass works |
| B4 (Audit log) | Register/login/admin events recorded; admin viewer endpoint works |
| B5 (Security tests) | All security tests pass |
| C1 (Self-test gate) | `scripts/self_test.sh` exits 0 on green, non-zero on failure |
| C2 (Smoke test) | `scripts/smoke_test.sh` passes against a running compose stack |
| **Regression** | All 452 existing tests still pass |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| Resend key absent in dev / test | Dev-mode logging fallback keeps everything testable offline |
| Email sending blocks request path | Always enqueue via the job queue; never send inline |
| Redis-backed limiter adds a failure mode | Fall back to in-memory limiter on Redis outage (same pattern as `core/cache`) |
| Password-reset enumeration leak | Identical response whether or not email exists; rate-limit the endpoint |
| CSRF breaks the dashboard | Attach `X-CSRF-Token` in `lib/api.ts`; TestClient tests cover the flow |
| Digest send failures spam logs | Logged + recorded in `email_events`; never raise out of the job |
| rq-scheduler not installed | It is optional; threading fallback keeps weekly sends working |

---

## Sprint 07 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_07.md
2. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/core/tasks.py
3. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/api/security.py
4. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/api/routes/auth.py
5. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/db/models.py

Then execute Sprint 07 from SPRINT_07.md, in this order:

TRACK A — EMAIL SERVICE:

A1. Create phd_aggregator/core/email.py — send_email(to, subject, html, text) using httpx POST to https://api.resend.com/emails with RESEND_API_KEY. Dev mode (no key): log instead of send. Create tests/test_email.py.
A2. Create phd_aggregator/core/digest.py — build_digest(profile, top_positions, top_supervisors) returning {subject, html, text}. Only match_score > 0.85, max 5 positions, max 5 supervisors; each item has why/deadline/funding/next-action. Deterministic sort (score desc, deadline asc). Create tests/test_digest.py.
A3. Add to phd_aggregator/core/tasks.py: send_digest_job(profile_id) + enqueue_digest_job(). Add rq-scheduler to requirements.txt; weekly cron + threading fallback. Test with a fake profile.
A4. Create phd_aggregator/api/routes/email.py — POST /api/email/webhook (verify RESEND_WEBHOOK_SECRET signature), GET /api/email/unsubscribe (signed HMAC token), POST /api/email/preview-digest. Register in api/app.py. Create tests/test_email_routes.py.
A5. Digest tests: ≤5 positions, only >0.85, sort order, unsubscribe round-trip, dev-mode skip, webhook signature reject.

TRACK B — AUTH HARDENING:

B1. Create phd_aggregator/core/ratelimit.py — RedisRateLimiter (sliding window via core.cache._get_redis()) with in-memory fallback. Swap the internals of api/security.py register_limiter/login_limiter to use it WITHOUT changing their public API. Add login lockout after N failures. Tests: 200/429 with fake Redis + fallback.
B2. Add PasswordReset + EmailVerification models to db/models.py (token_hash SHA-256, expires_at, used_at) + email_verified/email_verified_at on User. Add /api/auth/forgot-password, /reset-password, /verify-email, /resend-verification. Identical response whether email exists or not. Tokens single-use, 24h, hashed. Alembic migration. Tests.
B3. Add CSRF: double-submit cookie pattern — login sets a csrf_token cookie; a middleware requires X-CSRF-Token on mutating cookie-auth requests; Bearer requests and /api/email/webhook exempt. Update dashboard/lib/api.ts to attach the header. Tests.
B4. Add AuditEvent model + api/security.py log_audit() helper. Record register/login success/fail/reset/verify/unsubscribe/invite/admin actions. Admin endpoint GET /api/admin/audit. Tests.
B5. Security tests pass: limiter, reset-token single-use, CSRF 403/ok, audit rows.

TRACK C — SELF-TEST AUTOMATION:

C1. Create scripts/self_test.sh (offline self-test + pytest + npm test + warn-only live sweep) and scripts/self_test_fast.sh (steps 1-3). Both exit non-zero on failure.
C2. Create scripts/smoke_test.sh — health, ready, dashboard, register→login→build-profile→matches→cleanup (uses CIK_SMOKE_TEST=1).

RULES:
- Every new endpoint has tests (fastapi TestClient, in-memory SQLite).
- Every backend change: python -m pytest tests/ -q must stay green (452 existing).
- No breaking changes to existing endpoints or the CLI.
- Emails are always sent via the job queue, never inline.
- The dashboard must attach X-CSRF-Token on mutations.
```
