# Developer API — `/api/v1`

The versioned, public REST API for third-party integration (Sprint 08).
Institutions and external tools can read opportunities/matches/supervisors and
submit feedback under per-developer **API keys** — scoped, rate-limited,
quotable and revocable.

- Interactive docs: `/docs` (Swagger) and `/redoc`.
- Versioning policy: everything under `/api/v1/` is **stable**. Backwards
  incompatible changes require a new version (`/api/v2/...`). The internal
  versionless routes may change at any time and are not for external use.

---

## 1. Get an API key

1. Register / log in to the dashboard.
2. Open **API Keys** (`/keys`).
3. Create a key with a name and a scope set.
4. Copy the raw key **once** — it is never shown again and never stored by us
   (only its SHA-256 hash is kept; see [Security](#6-security)).

Default scopes: `read:profile`, `read:matches`, `read:opportunities`,
`read:supervisors`. A key is pepper-limited at **60 requests/minute** with no
daily quota unless an admin sets one (`quota_limit`).

Keys can be revoked or rotated at any time. Rotating issues a fresh key with
the same settings and immediately invalidates the old one.

---

## 2. Authenticate

Send the key as a Bearer token:

```
Authorization: Bearer cik_0f9c2b4a...
```

A user JWT works too (all non-admin scopes; `admin` only for admin accounts),
but API keys are the supported integration path.

| Result | Meaning |
|--------|---------|
| 401 | Missing, unknown, revoked, or expired key / token |
| 403 | Authenticated but missing the required scope |
| 429 | Rate limit or daily quota exceeded (see headers) |
| 422 | Validation error |

---

## 3. Rate limits & quotas

Every `/api/v1` response carries:

| Header | Meaning |
|--------|---------|
| `X-RateLimit-Limit` | Requests allowed per rolling minute (default 60, or the key's `rate_limit`) |
| `X-RateLimit-Remaining` | Requests left in the current window |
| `X-RateLimit-Reset` | Unix epoch seconds when the window resets |

On `429` additionally:

- `Retry-After` — seconds to wait (per-minute reset, or midnight UTC for a
  daily quota).

Quota semantics: a key with `quota_limit = N` may make `N` requests per UTC
day; exceeding it returns `429` with `Retry-After` until midnight UTC. Usage
per key/day is visible in the dashboard (API Keys → Usage) and over
`GET /api/v1/apikeys/{id}/usage`.

A global per-IP guardrail also caps undifferentiated traffic to the public API.

---

## 3. Response envelope & errors

Lists:

```js
{
  "data": [ ... ],
  "meta": { "page": 1, "limit": 20, "total": 123, "pages": 7 }
}
```

Single resources:

```js
{ "data": { ... } }
```

Errors:

```js
{ "error": { "code": "http_error", "message": "Missing required scope: read:matches" } }
```

Validation errors use `code: "validation_error"` and `detail: [ ... ]` with the
per-field Pydantic errors.

---

## 4. Endpoints

All read endpoints support standard query filters and pagination
(`page`, `limit`, with `limit <= 200`).

| Method & path | Scope | Description |
|---------------|-------|-------------|
| `GET /api/v1/me` | `read:profile` | The caller's active profile (`data: null` if none) |
| `GET /api/v1/matches` | `read:matches` | Scored matches for the active profile (`min_score`, `page`, `limit`) |
| `GET /api/v1/opportunities` | `read:opportunities` | Opportunities, filters `country`/`source`/`type` |
| `GET /api/v1/supervisors` | `read:supervisors` | Ranked supervisors, filters `country`/`field` |
| `POST /api/v1/bookmarks` | `write:bookmarks` | Body `{ "opportunity_id": 42 }` → adds a bookmark |
| `DELETE /api/v1/bookmarks/{id}` | `write:bookmarks` | Removes a bookmark from your active profile |
| `POST /api/v1/feedback` | `write:feedback` | Body `{ "match_id": 42, "helpful": true, "comment": "..." }` |

Anonymous (no key) reads of opportunities/supervisors remain available on the
internal paths but are not a stable public contract — use `/api/v1` with a key.

---

## 5. Key management (developer-facing, JWT required)

These operate on **your own** keys with a user token:

| Method & path | Purpose |
|---------------|---------|
| `GET /api/v1/apikeys` | List your keys (prefix, scopes, status — no hashes, no raw keys) |
| `POST /api/v1/apikeys` | Create, body `{name, scopes?, expires_at?}` → returns `raw_key` once |
| `PATCH /api/v1/apikeys/{id}` | Rename / change scopes |
| `DELETE /api/v1/apikeys/{id}` | Revoke (soft) |
| `POST /api/v1/apikeys/{id}/rotate` | Issue a new key, revoke the old one |
| `GET /api/v1/apikeys/{id}/usage` | Per-day request counts + quota settings |

Admins additionally have `/api/admin/apikeys*` endpoints to list all keys,
revoke any key, and override `quota_limit` / `rate_limit`.

---

## 6. Security

- Raw keys are **never stored**: the DB keeps only `sha256(key)`; the UI shows
  a 12-character prefix.
- Keys are scoped, so a leaked key carries only its granted permissions.
- Rotate immediately if a key leaks; revocation is effective on the next call.
- Transport: the API is HTTPS-terminated in production; keys must never be
  placed in public repos, client-side bundles, or logs.

---

## 7. Examples

### curl

```bash
KEY="cik_your_key_here"
# Top 5 matches
curl -s "$BASE/api/v1/matches?limit=5" \
  -H "Authorization: Bearer $KEY" | jq '.data[].title'
# Recent opportunities in Germany
curl -s "$BASE/api/v1/opportunities?country=Germany&limit=10" \
  -H "Authorization: Bearer $KEY"
```

### Python (10 lines)

```python
import requests
BASE, KEY = "http://localhost:8000", "cik_your_key_here"
h = {"Authorization": f"Bearer {KEY}"}
r = requests.get(f"{BASE}/api/v1/opportunities", params={"country": "Germany"}, headers=h)
r.raise_for_status()
[print(o["title"], o.get("deadline", "")) for o in r.json()["data"]]
```

### JavaScript

```js
const res = await fetch(`${BASE}/api/v1/matches`, {
  headers: { Authorization: `Bearer ${KEY}` },
});
const { data, meta } = await res.json();
console.log(data, meta.total);
```