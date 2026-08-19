# Security

Security posture for the Astra private beta. This is the walkthrough
of every item that must hold before opening the beta. Most items are code already in the
repo; the "status" column is what to verify at deploy time (docs/BETA_CHECKLIST.md ticks
them off).

## At a glance

| Area | Setting | Where |
|------|---------|-------|
| Password hashing | bcrypt, cost 12 (stdlib default) | `api/security.py` |
| Sessions | HS256 JWT via PyJWT, 1 h expiry, httpOnly `cik_token` cookie, `Secure` + `SameSite=Strict` | `api/routes/auth.py` |
| CSRF | Double-submit cookie for cookie-authenticated mutations | `api/app.py` → `CsrfMiddleware` |
| Rate limits | register 3/h, login 5/min, reset 5/h, verify 5/h per IP; API key 60/min + per-IP guardrail | `api/security.py`, `api/deps.py` |
| Transport | TLS terminated by Caddy; HSTS, `X-Frame-Options: DENY`, nosniff headers | `caddy/Caddyfile`, `SecurityHeadersMiddleware` |
| API keys | Only SHA-256 stored; `cik_` prefix; revoke/rotate; scopes | `api/routes/apikeys.py` |
| SSRF | Block loopback/private/link-local/link to be fetched by the crawler | `core/http.py` (Sprint 10, D1) |
| Input | Pydantic v2 validation on every route; OpenAPI-typed bodies | all `api/routes/*` |
| Secrets | `.env` gitignored; `ASTRA_SECRET_KEY` enforced in prod compose | `.gitignore`, `docker-compose.prod.yml` |
| Invites | `INVITES_REQUIRED=1` gates registration behind an invite code | `api/routes/invites.py` |

## Detailed checklist

### Secrets
- [x] No secrets in the repo: `.env*` is gitignored (only `.env.example` tracked); repo has no committed keys.
- [ ] Generate a fresh `ASTRA_SECRET_KEY` at deploy time (`python -c "import secrets; print(secrets.token_urlsafe(48))"`); rotate after any suspected leak.
- [ ] Provider keys (Groq/Gemini/ADS) live only in the VPS `.env`, never in CI logs (no CI configured yet).
- [ ] `BACKUP_AGE_PRIVATE_KEY` lives off the VPS (see `docs/BACKUPS.md`).

### Authentication & access
- [x] bcrypt cost 12; passwords require ≥ 8 chars.
- [x] JWT expires after 1 h; cookies are httpOnly, `Secure`, `SameSite=Strict`.
- [x] Redis-backed rate limits on register/login/reset/verify; degraded (in-process) when Redis is absent.
- [x] Registration gated by invite codes (operator turns on `INVITES_REQUIRED=1` in prod `.env`).
- [x] Session invalidation on password change occurs via re-login flow (tokens are stateless HS256).
- [ ] Verify a full HTTPS auth flow with the smoke test before opening invites.

### Transport & headers
- [x] Caddy terminates TLS with automatic Let's Encrypt.
- [x] HSTS `max-age=31536000` on both hosts; `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `X-XSS-Protection`.
- [x] Auth cookie is `Secure` → only works over HTTPS (a plain-HTTP deploy simply cannot log in).
- [ ] Firewall: only 22/80/443 open on the VPS (`ufw`).

### Input validation & abuse
- [x] Every body is a Pydantic model; `422` on malformed input (v1 endpoints use the `{error: {code, message}}` envelope).
- [x] SSRF guard shipped in `core/http.py`: rejects non-http(s) schemes, private-IP literals, and hostnames resolving to private ranges; unit-tested and configurable via `ASTRA_SSRF_GUARD`.
- [x] Global per-IP guardrail on `/api/v1` and strict per-key rate limits.
- [x] Audit log for admin actions, login, register, consent, and erase (`audit_events`).

### Data & dependencies
- [x] `pip-audit` clean; `npm audit` clean (next bumped to 16.3.0, python-jose replaced by PyJWT to drop the vulnerable `ecdsa` dep).
- [x] GDPR surface: data-export, consent, and right-to-erasure endpoints (anonymizes analytics rather than hard-deleting them).
- [x] Backups encrypted with `age`, pruned, with a documented restore drill.
- [x] Only the minimal PII is stored (email + profile); profile `raw_text` is user-controlled; email bounces tracked via Resend webhook.
- [ ] Re-run `scripts/self_test.sh`, pytest, npm test, and `next build` right before each beta release (the four gates).

## Residual risks (documented, accepted for the beta)

1. **DNS rebinding** — the SSRF guard checks resolution at request time but does not
   pin the connection to the resolved IP. A hostile DNS server could in theory swap the
   IP between check and connect. Mitigation: seed URLs are operator-controlled, and
   per-host resolutions are cached. A hardened crawler would pin IPs + set Host headers;
   tracked for a later phase.
2. **Playwright under hardened container** — `cap_drop: ALL` + `no-new-privileges` may
   break headless-browser fallback on some kernels. The code degrades gracefully (JS
   pages skipped), which is why regular crawling of JS-only sources should be verified in
   staging.
3. **No WAF** — rate limits and validation live in the app itself, not a web
   application firewall. Adequate for an invite-only beta.

## OWASP Top-10 quick review

| Area | Verdict |
|------|---------|
| A01 Broken access control | Verified — per-user scoping in every repo; admin endpoints check role; 404s hide ownership |
| A02 Cryptographic failures | bcrypt + HS256 w/ strong key; TLS 1.2+ via Caddy |
| A03 Injection | SQLAlchemy ORM everywhere; no raw SQL in routes; HTML escaping in the dashboard |
| A04 Insecure design | Invite-gated beta, rate limited, audit logged, GDPR surface present |
| A05 Misconfig | `.env.example` documented; prod compose enforces required secrets; headers fortified |
| A06 Vulnerable components | `pip-audit`/`npm audit` clean today; re-run on every release |
| A07 Auth failures | HS256 key rotation documented; rate limits + 1 h expiry |
| A08 Integrity | API keys hashed; CSRF protected; hmac-signed unsubscribe links |
| A09 Logging/monitoring | JSON logs with request ids; Sentry; uptime checks; audit trail |
| A10 SSRF | Guard shipped (see residual risk 1) |