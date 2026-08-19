# API Reference

The Astra API is a FastAPI app. Base URL is `http://localhost:8000`
in dev (`NEXT_PUBLIC_API_URL` / `CORS_ORIGINS` control it in production).
Interactive OpenAPI docs are served at **`/docs`** (Swagger) and `/redoc`.

> **Two surfaces.** The **versioned public API** (`/api/v1`, API-key auth,
> stable contract, envelope + scope model) is documented separately in
> [DEVELOPER_API.md](./DEVELOPER_API.md). The endpoints below are the **internal**
> API consumed by the dashboard: they may evolve freely and are **not** a stable
> contract for external integrations.

All endpoints accept and return JSON. Public endpoints are unauthenticated;
everything else requires a Bearer token (see [Authentication](#authentication)).

---

## Endpoint index

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | — | Liveness probe |
| GET | `/ready` | — | Readiness probe (DB check) |
| GET | `/api/fields` | — | List available field profiles |
| POST | `/api/auth/register` | — | Create an account (optional invite) |
| POST | `/api/auth/login` | — | Get a token |
| POST | `/api/auth/refresh` | ✓ | Refresh the token |
| GET | `/api/auth/me` | ✓ | Current user |
| GET | `/api/profile` | ✓ | Active profile |
| POST | `/api/profile/build` | ✓ | LLM-extract profile from CV text |
| PUT | `/api/profile` | ✓ | Update the active profile |
| GET | `/api/opportunities` | — | Paginated opportunities + filters |
| GET | `/api/opportunities/{id}` | — | Single opportunity |
| GET | `/api/matches` | ✓ | Matches scored against your profile |
| POST | `/api/matches/{match_id}/feedback` | ✓ | 👍/👎 relevance feedback |
| GET | `/api/supervisors` | — | Supervisor list + filters |
| GET | `/api/supervisors/{id}` | — | Single supervisor |
| GET | `/api/bookmarks` | ✓ | Your bookmarks |
| POST | `/api/bookmarks` | ✓ | Bookmark an opportunity |
| DELETE | `/api/bookmarks/{id}` | ✓ | Remove a bookmark |
| GET | `/api/preferences` | ✓ | Digest preference |
| POST | `/api/preferences` | ✓ | Update digest preference |
| POST | `/api/pipeline/run` | — | Start a background pipeline run |
| GET | `/api/pipeline/status` | — | Poll a pipeline run |
| GET | `/api/jobs/{job_id}` | — | Job status |
| DELETE | `/api/jobs/{job_id}` | — | Cancel a queued job |
| POST | `/api/invites` | admin | Create an invite code |
| GET | `/api/invites` | admin | List invites + usage |
| POST | `/api/invites/{code}/redeem` | — | Validate an invite code |
| GET | `/api/admin/pool-status` | admin | DB connection pool metrics |
| GET | `/api/admin/metrics` | admin | Aggregated beta metrics |

---

## Authentication

1. `POST /api/auth/register` (or `/api/auth/login`) returns:

   ```json
   { "access_token": "eyJhbGciOi...", "token_type": "bearer" }
   ```

2. Send it on every authenticated request:

   ```
   Authorization: Bearer eyJhbGciOi...
   ```

Tokens are signed HS256 JWTs with a 1-hour expiry (`sub` = user id). Login also
sets an `httpOnly` `cik_token` cookie (`SameSite=Strict`) for browser clients.
`POST /api/auth/refresh` issues a fresh token for an authenticated session.

**Admin** endpoints additionally require the user's role to be `admin`
(see `GETTING_STARTED.md §4` for bootstrapping an admin via CLI). Non-admins get
`403`.

---

## Rate limiting

Auth endpoints are rate-limited per client IP (in-memory, resets on restart):

| Endpoint | Limit |
|----------|-------|
| `POST /api/auth/register` | 3 per hour |
| `POST /api/auth/login` | 5 per minute |

Responses carry headers:

```
X-RateLimit-Limit: 3
X-RateLimit-Remaining: 2
```

When exceeded the API returns `429 Too Many Requests`.

---

## Error codes

| Code | Meaning |
|------|---------|
| 400 | Malformed request |
| 401 | Missing/invalid token (`WWW-Authenticate: Bearer`) |
| 403 | Authenticated but not allowed (admin-only route) |
| 404 | Resource or active profile not found |
| 409 | Conflict (duplicate email, job already started) |
| 422 | Validation error or bad invite code |
| 429 | Rate limit exceeded / too many pipeline runs |
| 503 | Dependency not ready (DB down) |

Error bodies:

```json
{ "detail": "Email already registered" }
```

---

## Endpoints

### Meta

**GET /health**

```json
{ "status": "ok", "version": "0.1.0" }
```

**GET /ready** — `200` when the DB is reachable, else `503`.

```json
{ "status": "ready", "db": "ok", "llm": true }
```

**GET /api/fields**

```json
{ "default": "astronomy", "profiles": ["astronomy", "biology"] }
```

---

### Auth

**POST /api/auth/register**

```json
{ "email": "you@example.com", "password": "SuperSecret1", "invite_code": "abc123" }
```

`invite_code` is required only when `INVITES_REQUIRED=1`; otherwise optional.
→ `201`:

```json
{ "user_id": 1, "email": "you@example.com" }
```

**POST /api/auth/login** → `200` with the token (see [Authentication](#authentication)).

**POST /api/auth/refresh** (auth) → fresh token.

**GET /api/auth/me** (auth)

```json
{ "user_id": 1, "email": "you@example.com" }
```

---

### Profile

**GET /api/profile** (auth) — `404` if none.

```json
{
  "domain": "astronomy",
  "subfield": "interstellar medium",
  "methods": ["radio interferometry"],
  "tools": ["Python", "LOFAR"],
  "skills": ["data analysis", "dust polarization"],
  "experience_level": "phd_student",
  "target_roles": ["PhD researcher"],
  "countries_preferred": ["Germany", "Netherlands"],
  "funding_requirement": "fully funded",
  "constraints": [],
  "confidence": 0.9,
  "raw_text": "I am a PhD student in astronomy..."
}
```

**POST /api/profile/build** (auth) — body `{ "raw_text": "<CV text>" }`.
Runs the LLM extractor; `422` if extraction fails. → `201` with the same shape.

**PUT /api/profile** (auth) — partial update; any subset of the fields above.

---

### Opportunities

**GET /api/opportunities** (public) — query params `country`, `source`, `type`,
`page` (default 1), `limit` (default 20, max 100).

```json
{
  "items": [
    {
      "id": 42,
      "source": "euraxess",
      "title": "PhD in radio astronomy",
      "institution": "MPIfR",
      "department": null,
      "country": "Germany",
      "city": "Bonn",
      "url": "https://euraxess.ec.europa.eu/...",
      "type": "phd",
      "field": "astronomy",
      "subfield": null,
      "topics": ["interstellar medium"],
      "deadline": "2026-09-30T00:00:00",
      "posted_date": "2026-07-01T00:00:00",
      "effective_date": null,
      "freshness": "fresh",
      "relevance_score": 8.0,
      "short_description": "Doctoral project on radio astronomy.",
      "position_type": "phd",
      "is_new": true
    }
  ],
  "total": 120,
  "page": 1,
  "limit": 20,
  "pages": 6
}
```

**GET /api/opportunities/{opportunity_id}** → single object or `404`.

---

### Matches

**GET /api/matches** (auth) — query params `min_score` (0–1), `page`, `limit`
(max 200). Requires an active profile (`404` otherwise). Each item is an
opportunity enriched with:

```json
{
  "match_score": 0.91,
  "match_explanation": "Strong topic match: your astronomy/ISM aligns...",
  "topic_score": 0.9,
  "method_score": 0.8,
  "location_score": 1.0,
  "confidence": 0.9,
  "percentile": 97.4,
  "suggestions": ["radio interferometry"]
}
```

Results are deterministic per profile and cached (1 h TTL); they are
invalidated when the profile changes or a pipeline run completes.

**POST /api/matches/{match_id}/feedback** (auth)

```json
{ "helpful": true, "comment": "Very relevant to my LOFAR work" }
```

`match_id` must reference an existing opportunity. → `200` `{ "status": "ok",
"match_id": 7, "helpful": true }`.

---

### Supervisors

**GET /api/supervisors** (public) — query params `country`, `field`, `limit`.

**GET /api/supervisors/{supervisor_id}** → single object or `404`. Both return
`{ "id", "source", "name", "institution", "department", "country",
"profile_url", "email", "orcid", "topics", "methods", "recent_papers",
"fit_score", "confidence" }` wrapped in the standard `{ "items", "total", ... }`
paginator.

---

### Bookmarks

**GET /api/bookmarks** (auth) → `{ "items": [ { "id", "opportunity_id",
"created_at", "opportunity": {...} } ], "total", ... }`.

**POST /api/bookmarks** (auth) — `{ "opportunity_id": 42 }` → `201`.

**DELETE /api/bookmarks/{bookmark_id}** (auth) → `200` on success.

---

### Preferences

**GET /api/preferences** (auth)

```json
{ "digest_enabled": false, "frequency": null }
```

**POST /api/preferences** (auth) — `{ "digest_enabled": true }` →
`{ "digest_enabled": true, "frequency": "weekly" }`.

---

### Pipeline & jobs

**POST /api/pipeline/run** — body `{ "sources": ["euraxess"], "country":
"Germany" }` (both optional). → `202`:

```json
{ "status": "started", "run_id": "9f2c0a1b3c4d" }
```

The run executes on a background **worker** (rq via Redis when configured, an
in-process thread otherwise — see `DEPLOYMENT.md`). >3 concurrent runs return
`429`.

**GET /api/pipeline/status?run_id=...**

```json
{ "job_id": "9f2c0a1b3c4d", "status": "completed", "records": 132 }
```

Statuses: `queued`, `running`, `completed`, `failed`, `cancelled`. On failure an
`error` string is included.

**GET /api/jobs/{job_id}** — same shape as pipeline status.

**DELETE /api/jobs/{job_id}** — cancels a *queued* job → `200`; `409` if already
started; `404` if unknown.

---

### Invites (private beta)

**POST /api/invites** (admin) — body `{}` (optional `{ "note": "..." }`). → `201`:

```json
{ "id": 3, "code": "abCdEf012345", "created_by": 1, "used_by": null, "used_at": null, "used": false }
```

**GET /api/invites** (admin)

```json
{
  "items": [ { "id": 3, "code": "abCdEf012345", "created_by": 1, "used_by": 2, "used": true } ],
  "created": 5,
  "redeemed": 2,
  "pending": 3
}
```

**POST /api/invites/{code}/redeem** (public) — validates the code without
consuming it:

```json
{ "valid": true, "code": "abCdEf012345" }
```

`422` for unknown/used codes. Consumption happens on registration.

---

### Admin

**GET /api/admin/pool-status** (admin) — SQLAlchemy pool metrics (QueuePool for
PostgreSQL; SQLite reports `enabled: false`).

```json
{
  "engine": "postgresql",
  "pool": "QueuePool",
  "enabled": true,
  "pool_size": 5,
  "max_overflow": 10,
  "timeout_seconds": 30,
  "recycle_seconds": 1800,
  "status": { "checkedout": 0, "size_overflow": 0, "size": 0 }
}
```

**GET /api/admin/metrics** (admin) — aggregated beta metrics for the admin
dashboard:

```json
{
  "users": { "total": 12, "active": 6, "profiles_built": 9 },
  "content": {
    "opportunities": 320, "supervisors": 45, "matches": 88,
    "sources": [ { "source": "euraxess", "records": 200, "last_posted": "2026-08-01T..." } ],
    "feedback": { "total": 40, "helpful": 31 }
  },
  "api": { "requests": 1050, "errors": 2, "error_rate": 0.002, "avg_latency_ms": 11.4, "p95_latency_ms": 38.0, "median_latency_ms": 9.2 },
  "jobs": { "backend": "in-process", "pending": 0, "running": 0, "completed": 7, "failed": 0, "total": 7 },
  "invites": { "created": 8, "redeemed": 4, "pending": 4 },
  "updated_at": "2026-08-04T00:00:00Z"
}
```
