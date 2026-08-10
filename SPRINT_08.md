# Sprint 08: Public Developer API + API Token Management

**Duration:** Weeks 3-4 (target: 2026-09-01 → 2026-09-14)
**Goal:** Open a versioned public REST API (`/api/v1`) with per-developer API
keys (scoped, rate-limited, quotable, revocable) plus the dashboard + admin
surfaces to manage them. Third parties and institutions can then integrate
against the platform.

---

## What shipped in Sprints 01-07 (for context)

| Item | Status |
|------|--------|
| Full backend + dashboard + docker | DONE |
| Security baseline (JWT, bcrypt, Redis rate limit, CSRF, audit log) | DONE (Sprint 07) |
| Email service (Resend, weekly digest, webhooks, unsubscribe) | DONE (Sprint 07) |
| Scriptable self-test + smoke-test gates | DONE (Sprint 07) |
| Tests: 452 + Sprint 07 additions passing | DONE |

---

## Track A: API Key Model + Lifecycle

### A1: `ApiKey` model + repositories
**Effort:** 1 day
**Deliverable:** `db/models.py` + `db/repositories.py` + Alembic migration

```python
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))          # "Production ML app"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256
    key_prefix: Mapped[str] = mapped_column(String(12))     # cik_xxxxxxxx visible prefix
    scopes: Mapped[str] = mapped_column(Text)               # JSON list, e.g. ["read:matches"]
    quota_limit: Mapped[Optional[int]] = mapped_column(Integer)  # per-day request cap
    rate_limit: Mapped[Optional[int]] = mapped_column(Integer)   # per-minute cap (override)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
```

- **Never store the raw key** — store `sha256(raw)`. The raw key is shown
  exactly once at creation (`cik_` + 40 hex chars, `secrets.token_hex(20)`).
- **Key prefix**: store the first 12 chars so the UI can show "which key" with
  a badge without leaking the secret.
- Repos: `ApiKeyRepo.create/get_by_hash/list_for_user/revoke/rotate/update_usage`.
- Alembic migration (`alembic revision --autogenerate`).

### A2: Key lifecycle endpoints — `api/routes/apikeys.py`
**Effort:** 1 day
**Deliverable:** `api/routes/apikeys.py` + `tests/test_apikeys.py`

Scoped to the authenticated user (a developer manages their *own* keys):

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/apikeys` | GET | user JWT | List own keys (prefix, name, scopes, last_used, revoked?, expiry — no hash) |
| `/api/v1/apikeys` | POST | user JWT | `{name, scopes, expires_at?}` → returns `{key: "cik_..."}` **once** |
| `/api/v1/apikeys/{id}` | PATCH | user JWT | Rename, change scopes, rotate |
| `/api/v1/apikeys/{id}` | DELETE | user JWT | Revoke (soft: set `revoked_at`, keep audit) |
| `/api/v1/apikeys/{id}/rotate` | POST | user JWT | Issue a new key, revoke the old one |
| `/api/v1/apikeys/{id}/usage` | GET | user JWT | Per-day request counts + current quota |

- Available scopes (whitelist enforced server-side):
  `read:profile`, `read:matches`, `read:opportunities`, `read:supervisors`,
  `write:bookmarks`, `write:feedback`, `admin` (admin-only).
- Admin endpoints in `api/routes/admin.py`: list all keys, revoke any key,
  override quotas, view key health (usage, last-used, error rate).

### A3: Dashboard API-key page — `dashboard/app/settings/page.tsx` (+ new page)
**Effort:** 1 day
**Deliverable:** `dashboard/app/keys/page.tsx` + `lib/api.ts` additions

- Page: list keys (name, prefix badge, scopes, last used, status), create key
  (with "copy key once" dialog + warning it won't be shown again), revoke,
  rotate, and a per-key usage bar chart.
- Wire into `Nav.tsx` (Settings → "API Keys").
- Tests: `dashboard/__tests__/apikeys.test.tsx` — create flow renders the
  one-time key, revoke asks for confirmation, empty state.

---

## Track B: Authentication for the Public API

### B1: API-key auth dependency — `api/deps.py`
**Effort:** 0.5 days
**Deliverable:** `api/deps.py` + tests

Add a second auth path alongside `get_current_user`:

```python
def get_api_principal(
    credentials = Depends(_http_bearer),
    session = Depends(get_db),
) -> Principal:
    """Resolve either a user JWT (Authorization: Bearer <jwt>) or an API key
    (Authorization: Bearer cik_...) into a Principal {user_id, scopes}."""
```

- If the token starts with `cik_`: look up `sha256(token)` in `api_keys`,
  reject if revoked/expired, update `last_used_at` (throttled, ~1/min per key
  to avoid a write per request).
- Otherwise fall through to `decode_access_token` (existing JWT path).
- **Scope enforcement helper**:

```python
def require_scope(scope: str):
    """Dependency that fails 403 unless the API principal holds `scope`."""
```

- The existing user-facing routes keep using `get_current_user` — they are
  unaffected. The *public* `/api/v1` routes use `get_api_principal` + scope
  guards.

### B2: Per-key rate limiting + quota metering — `core/ratelimit.py` addition
**Effort:** 1 day
**Deliverable:** `core/ratelimit.py` + `api/routes/middleware.py` or per-route

- **Per-minute rate limit**: reuse `RedisRateLimiter` keyed on
  `rate:apikey:{key_id}`; default 60 req/min (configurable per key).
- **Per-day quota**: counter key `quota:apikey:{key_id}:{YYYYMMDD}`; when the
  quota is exceeded return `429` with `X-RateLimit-*` headers + a
  `Retry-After`.
- Global guardrails: total requests per IP (public API) capped to prevent a
  single consumer saturating the box.
- Metering: increment per-request counters so `/usage` and admin can report
  real numbers. Counts live in Redis with a 24h TTL bucket + a nightly
  rollup into `api_key_usage` rows (for admin charts).

### B3: Versioned public routes — `api/routes/v1/`
**Effort:** 1 day
**Deliverable:** `api/routes/v1/{opportunities,matches,profile,supervisors}.py`

Expose a **stable, documented subset** under `/api/v1` (the internal routes
stay at their current paths and may evolve freely):

| Route | Scope required | Notes |
|-------|----------------|-------|
| `GET /api/v1/me` | `read:profile` | active profile for the key's user |
| `GET /api/v1/matches` | `read:matches` | paginated, with explanations + percentile |
| `GET /api/v1/opportunities` | `read:opportunities` | filters: country/source/type, pagination |
| `GET /api/v1/supervisors` | `read:supervisors` | filters + sorting |
| `POST /api/v1/bookmarks` | `write:bookmarks` | bookmark an opportunity |
| `DELETE /api/v1/bookmarks/{id}` | `write:bookmarks` | remove a bookmark |
| `POST /api/v1/feedback` | `write:feedback` | match feedback |

- These thin wrappers reuse the same repos/services as the internal routes —
  **no duplicated business logic**.
- Response envelope: `{"data": ..., "meta": {"page": ..., "pages": ...}}` for
  lists; errors follow a fixed shape `{"error": {"code", "message", "detail"?}}`.
- Keep the internal routes as-is (backwards compatibility — release rule).

### B4: Public API tests
**Effort:** 0.5 days

- Test: create key → call `/api/v1/me` with `cik_...` → 200.
- Test: revoked key → 401; expired key → 401; bad prefix → 401.
- Test: missing scope → 403; wrong scope → 403.
- Test: per-key rate limit (60/min) → 429 with headers.
- Test: quota exceeded → 429 with `Retry-After`.
- Test: internal routes still work with a user JWT (no regression).

---

## Track C: Developer Experience

### C1: OpenAPI + docs — `docs/API.md` update + `docs/DEVELOPER_API.md`
**Effort:** 0.5 days

- Publish the `/api/v1` schema (`/docs` already exposes OpenAPI; add a
  `description` + servers entry).
- `docs/DEVELOPER_API.md`: getting an API key, auth header example,
  endpoint reference, scope table, rate limits, error codes, pagination, curl
  examples, and a "quota management" section.
- Sample integrations: a 10-line Python snippet and a JS fetch example.

### C2: Dashboard "Developers" section polish
**Effort:** 0.5 days

- Usage chart component (per-day request counts, last 14 days).
- "Last used" relative time, revoke confirmation, rotate flow.
- Empty state: "No API keys yet — create one to integrate."

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (ApiKey model) | Migration applied; raw keys never stored; prefix + hash kept |
| A2 (Lifecycle) | Create/revoke/rotate/list/usage work with tests; raw key shown once |
| A3 (Dashboard) | Keys page: create (copy-once), revoke, rotate, usage chart |
| B1 (Auth dep) | `get_api_principal` + `require_scope` enforce JWT vs key + scopes |
| B2 (Limits) | Per-key rate limit + daily quota via Redis; 429 + headers; metering works |
| B3 (v1 routes) | All v1 endpoints return the documented envelope; internal routes unchanged |
| B4 (Tests) | Key auth, scopes, revocation, limits, quota — all tested |
| C1 (Docs) | DEVELOPER_API.md accurate; OpenAPI shows v1 |
| C2 (Polish) | Dashboard Developers section usable on mobile |
| **Regression** | All existing tests (452 + Sprint 07) still pass |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| Raw key leaked in logs/DB | Store only SHA-256; show raw key once; keyed log redaction |
| Key enumeration via timing | Hash lookup via DB index; constant messages for bad/revoked/expired |
| Scope confusion (user vs key) | Distinct principal type + explicit `require_scope`; tests for every route |
| Quota/rate state lost on Redis restart | In-memory fallback (degraded, not broken); nightly DB rollup |
| Public API strains the DB (thousands of key calls) | Redis caching already covers matches/lists; v1 routes reuse the cache |
| Breaking internal routes while refactoring | v1 routes are wrappers; internal paths untouched |
| Developer keys shared between people | Per-key audit + last_used + admin revoke; documented in the guide |

---

## Sprint 08 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_08.md
2. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/api/deps.py
3. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/api/security.py
4. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/core/ratelimit.py
5. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/db/models.py
6. /home/mohammad-reza/career_intelligence_kit/dashboard/lib/api.ts

Then execute Sprint 08 from SPRINT_08.md, in this order:

TRACK A — API KEY MODEL + LIFECYCLE:

A1. Add ApiKey model to db/models.py (user_id, name, key_hash SHA-256 unique, key_prefix, scopes JSON, quota_limit, rate_limit, last_used_at, revoked_at, expires_at, created_at). Add ApiKeyRepo.create/get_by_hash/list_for_user/revoke/rotate/update_usage to db/repositories.py. Alembic migration. Test.
A2. Create api/routes/apikeys.py — GET/POST/PATCH/DELETE /api/v1/apikeys + /rotate + /usage (scoped to the authenticated user). Raw key returned exactly once on create (cik_ + 40 hex). Admin routes in api/routes/admin.py: list all, revoke, override quota. Register in api/app.py. Create tests/test_apikeys.py.
A3. Create dashboard/app/keys/page.tsx — list keys, create (copy-once dialog), revoke, rotate, usage chart. Add fetch functions to dashboard/lib/api.ts. Add nav link. Create dashboard/__tests__/apikeys.test.tsx.

TRACK B — AUTH FOR THE PUBLIC API:

B1. Add get_api_principal + require_scope to api/deps.py — Bearer cik_ tokens resolve via sha256 lookup (reject revoked/expired, update last_used throttled); other tokens go through the existing JWT path. Scope whitelist enforced.
B2. Extend core/ratelimit.py — per-key per-minute limiter + per-day quota (Redis, in-memory fallback), returning 429 with X-RateLimit-* and Retry-After. Nightly rollup of usage into api_key_usage rows.
B3. Create api/routes/v1/ — opportunities, matches, profile, supervisors, bookmarks, feedback under /api/v1 using get_api_principal + scope guards. Envelope: {"data": ..., "meta": {...}}; fixed error shape. Internal routes untouched.
B4. Public API tests: key auth, scopes (403), revocation (401), expiry, rate limit + quota (429 + headers), no regression on internal routes.

TRACK C — DEVELOPER EXPERIENCE:

C1. Update docs/API.md and create docs/DEVELOPER_API.md (get key, auth header, endpoint reference, scopes, limits, errors, curl examples). Ensure /docs shows the v1 schema.
C2. Polish the Developers section (usage chart, last-used, revoke confirm, empty state, mobile).

RULES:
- Raw API keys are NEVER stored or logged — only sha256.
- Every v1 endpoint has a test; internal routes must not change behavior.
- All changes keep python -m pytest tests/ -q green.
- Run npm test after dashboard changes.
```
