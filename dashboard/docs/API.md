# Astra — API Reference

Base URL: `http://localhost:8000` (dev). The dashboard reads
`NEXT_PUBLIC_API_URL` when deployed separately.

Interactive docs are also available from FastAPI/OpenAPI at `/docs`
(Swagger UI) and `/openapi.json`.

## Authentication

The API issues **JWT access tokens** that expire after **1 hour**.

- `POST /api/auth/register` creates an account.
- `POST /api/auth/login` returns `{ "access_token": "...", "token_type": "bearer" }`
  and also sets the token in a **httpOnly `cik_token` cookie** so browsers stay
  signed in without JS reading the token.
- `POST /api/auth/refresh` mints a new token from the existing cookie/session.
- `GET /api/auth/me` returns the current user.

To authenticate, send the token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Requests without a valid token on protected routes return `401`.

```
┌──────────┐   POST /api/auth/login   ┌──────────────┐
│ Dashboard│ ───────────────────────► │  FastAPI API │
│   (Next) │ ◄─────────────────────── │              │
└──────────┘ 200 {access_token} +      └──────────────┘
             Set-Cookie cik_token=…; HttpOnly
        │
        ▼
   subsequent calls with
   Authorization: Bearer <token>
```

### Auth error codes

| Code | Meaning |
|------|---------|
| 400 | Malformed request body |
| 401 | Invalid credentials, or missing/expired token |
| 409 | Email already registered |
| 422 | Invalid email format or password < 8 characters |
| 429 | Too many login/register attempts (per IP) |

Rate limiting is per IP:

- `POST /api/auth/register`: **3/hour**
- `POST /api/auth/login`: **5/minute**

Rate-limited responses include `X-RateLimit-Limit` and
`X-RateLimit-Remaining` headers.

---

## Endpoints

### Meta

#### `GET /health`

Liveness probe. Returns service health and version.

```json
{ "status": "ok", "version": "0.5.0" }
```

#### `GET /ready`

Readiness probe. Returns `200` only when the database is reachable **and** an
LLM provider is configured. `503` otherwise.

```json
{ "ready": true, "db": "ok", "llm": "configured" }
```

---

### Fields

#### `GET /api/fields`

Lists the built-in research field profiles (used by the Settings page).

```json
{
  "default": "astronomy",
  "profiles": ["astronomy", "physics", "geosciences"]
}
```

Unauthenticated.

---

### Auth

#### `POST /api/auth/register`

Create an account. Status `201`.

```json
// Request
{ "email": "astronomer@example.org", "password": "s3cret-pass" }
```

```json
// Response
{ "user_id": 1, "email": "astronomer@example.org" }
```

#### `POST /api/auth/login`

```json
// Request
{ "email": "astronomer@example.org", "password": "s3cret-pass" }
```

```json
// Response
{ "access_token": "eyJhbGciOiJIUzI1NiIs…", "token_type": "bearer" }
```

Also sets the httpOnly `cik_token` cookie.

#### `POST /api/auth/refresh`

Issues a fresh token. No body required (reads the cookie/current token).
Returns the same shape as login.

#### `GET /api/auth/me`

Requires auth. Returns the current user.

```json
{ "user_id": 1, "email": "astronomer@example.org" }
```

---

### Profile

All profile endpoints require auth.

#### `GET /api/profile`

Returns the user's active profile.

```json
{
  "domain": "astronomy",
  "subfield": "interstellar medium",
  "methods": ["radio interferometry"],
  "tools": ["LOFAR"],
  "skills": ["dust polarization"],
  "experience_level": "phd_student",
  "target_roles": ["postdoc"],
  "countries_preferred": ["Germany"],
  "funding_requirement": null,
  "constraints": [],
  "confidence": 0.9,
  "raw_text": "…"
}
```

`404` with `{ "detail": "No active profile" }` when no profile exists yet.

#### `POST /api/profile/build`

Extracts a structured profile from free text (CV/bio) using the LLM.
Status `201`.

```json
// Request
{ "raw_text": "I am a PhD student in astronomy, working on interstellar medium with radio interferometry (LOFAR)." }
```

Response is the same `UserProfile` shape as `GET /api/profile`.
`422` with `{ "detail": "Could not extract profile from text" }` when the LLM
is unavailable.

#### `PUT /api/profile`

Overwrites profile fields. Accepts a partial patch of any `UserProfile` keys
and returns the full updated profile.

```json
// Request
{ "domain": "physics", "target_roles": ["phd"] }
```

---

### Matches

Requires auth.

#### `GET /api/matches`

Returns the user's opportunities ranked by fit to their active profile.

Query params:

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `min_score` | float | `0.0` | Only matches with `match_score >= min_score` |
| `page` | int ≥ 1 | `1` | Page index |
| `limit` | int 1–200 | `20` | Page size |

Response is a paginated list. Each item is an `Opportunity` extended with
match metadata (see Sprint 05 explainability):

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
      "city": null,
      "url": "https://…",
      "type": null,
      "field": "astronomy",
      "subfield": "interstellar medium",
      "topics": ["magnetic fields", "polarization"],
      "deadline": "2026-10-01T00:00:00",
      "posted_date": null,
      "effective_date": null,
      "freshness": null,
      "relevance_score": 9,
      "short_description": "…",
      "position_type": "phd",
      "is_new": true,
      "match_score": 0.87,
      "match_explanation": "Strong topic match… This position is more relevant than 92% of opportunities. Consider learning: CMB analysis.",
      "topic_score": 0.9,
      "method_score": 0.75,
      "location_score": 0.95,
      "confidence": 0.9,
      "percentile": 92,
      "suggestions": ["CMB analysis"]
    }
  ],
  "total": 57,
  "page": 1,
  "limit": 20,
  "pages": 3
}
```

`404` when no active profile exists (build one first).

#### `POST /api/matches/{match_id}/feedback`

Records feedback on a match.

```json
// Request
{ "helpful": true, "comment": "Great match" }
```

```json
// Response
{ "status": "ok" }
```

---

### Opportunities

Public (no auth required).

#### `GET /api/opportunities`

Lists all crawled opportunities, paginated.

Query params:

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `country` | string | — | Exact country filter |
| `source` | string | — | Source name filter (e.g. `euraxess`) |
| `type` | string | — | Position type filter (e.g. `phd`) |
| `page` | int ≥ 1 | `1` | Page index |
| `limit` | int 1–100 | `20` | Page size |

Response shape mirrors the `items` entries above (without match fields).

#### `GET /api/opportunities/{opportunity_id}`

Single opportunity.

`404` `{ "detail": "Opportunity not found" }` when the id is unknown.

---

### Supervisors

Public (no auth required).

#### `GET /api/supervisors`

Lists supervisors, optionally filtered.

Query params:

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `country` | string | — | Exact country filter |
| `field` | string | — | Topic/department substring |
| `limit` | int 1–100 | `20` | Page size |

```json
{
  "items": [
    {
      "id": 7,
      "source": "ads",
      "name": "Dr. Lena Kraft",
      "institution": "MPIfR",
      "department": "Radio Astronomy",
      "country": "Germany",
      "profile_url": "https://orcid.org/0000-0001-2345-6789",
      "email": "lena@mpifr.de",
      "orcid": "0000-0001-2345-6789",
      "topics": ["interstellar medium", "magnetic fields"],
      "methods": ["radio interferometry"],
      "recent_papers": ["Faraday rotation in the ISM", "…"],
      "fit_score": 0.85,
      "confidence": 0.9
    }
  ],
  "total": 12
}
```

`orcid` is derived from the profile URL when present, else `null`.

#### `GET /api/supervisors/{supervisor_id}`

Single supervisor.

`404` `{ "detail": "Supervisor not found" }` when the id is unknown.

---

### Bookmarks

Require auth. Bookmarks belong to the signed-in user.

#### `GET /api/bookmarks`

Lists the current user's bookmarks with the nested opportunity.

```json
{
  "items": [
    {
      "id": 11,
      "opportunity_id": 42,
      "created_at": "2026-07-01T10:00:00",
      "opportunity": { "id": 42, "title": "PhD in radio astronomy", "…": "…" }
    }
  ],
  "total": 1
}
```

#### `POST /api/bookmarks`

Bookmark an opportunity. Status `201`.

```json
// Request
{ "opportunity_id": 42 }
```

```json
// Response
{ "id": 11, "opportunity_id": 42, "created_at": "2026-07-01T10:00:00", "opportunity": { "…": "…" } }
```

`404` if the opportunity does not exist; `409` `{ "detail": "Already
bookmarked" }` if already saved.

#### `DELETE /api/bookmarks/{bookmark_id}`

Removes a bookmark.

```json
// Response
{ "status": "ok" }
```

`404` `{ "detail": "Bookmark not found" }`.

---

### Pipeline

Require auth.

#### `POST /api/pipeline/run`

Triggers an async crawl + match run. Status `202`.

```json
// Request
{ "sources": ["euraxess", "findaphd"], "country": "Germany" }
```

```json
// Response
{ "status": "running", "run_id": "a1b2c3d4-…" }
```

`429` when another run is already in progress.

#### `GET /api/pipeline/status?run_id=…`

Polls a run.

```json
{ "run_id": "a1b2c3d4-…", "status": "completed", "records": 13 }
```

Status is one of `running`, `completed`, `failed`.
`404` `{ "detail": "Unknown run_id" }` for unknown ids.

---

## Security headers

Every response carries:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |

## CORS

Development allows `http://localhost:3000`. Production origins are configured
via the `CORS_ORIGINS` env var (comma-separated). Wildcard `*` is disabled
when credentials are used.

## Environment variables

See the project root `.env.example`. Key ones:

| Variable | Purpose |
|----------|---------|
| `ASTRA_SECRET_KEY` | JWT signing key (required in production) |
| `DATABASE_URL` | SQLAlchemy database URL |
| `LLM_DEFAULT_MODEL` | Primary LLM model id |
| `LLM_FALLBACK_MODEL` | Fallback LLM model id |
| `OPENALEX_MAILTO` | OpenAlex polite-pool contact email |
| `ADS_API_TOKEN` | NASA ADS API token |
| `CORS_ORIGINS` | Comma-separated allowed dashboard origins |
| `OPENAI_API_KEY` / `OLLAMA_HOST` | LLM provider credentials |

## Common error shape

All errors follow FastAPI's convention:

```json
{ "detail": "human readable message" }
```

`422` validation errors use the standard `{ "detail": [ { "loc": […], "msg": "…", "type": "…" } ] }` shape.
