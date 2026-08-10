# Sprint 10: Launch Readiness — CI/CD, Deploy, Backups, Load Test, Security Audit

**Duration:** Weeks 8-10 (target: 2026-10-06 → 2026-10-26)
**Goal:** Take the stack from "works on my machine / in compose" to a hardened
production service that comfortably serves ~1000 users: CI/CD pipelines, an
automated VPS deploy with TLS, encrypted backups with a tested restore,
load testing at scale, a security audit, and the public-facing launch assets
(landing page, legal pages, data-privacy endpoints).

---

## What shipped in Sprints 01-09 (for context)

| Item | Status |
|------|--------|
| Full backend + dashboard + docker + email + public API keys | DONE |
| Security: Redis rate limit, CSRF, audit log, password reset | DONE |
| Email service + digest + webhooks | DONE |
| AI features + AI ops (source monitor, feedback intel, self-healing, anomaly) | DONE |
| Scriptable self-test + smoke-test gates | DONE (Sprint 07) |
| Tests: 452 + Sprints 07-09 additions passing | DONE |

---

## Track A: CI/CD

### A1: GitHub Actions workflow — `.github/workflows/ci.yml`
**Effort:** 1 day
**Deliverable:** `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`

```yaml
# .github/workflows/ci.yml — runs on every PR and push to main
name: CI
on: [pull_request, push]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env: { POSTGRES_USER: cik, POSTGRES_PASSWORD: cik, POSTGRES_DB: cik }
        ports: ["5432:5432"]
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip }
      - run: pip install -r phd_aggregator/requirements.txt
      - run: python phd_aggregator.py --self-test          # offline gate
      - run: pytest phd_aggregator/tests/ -q                # sqlite + PG paths
        env: { DATABASE_URL: "postgresql://cik:cik@localhost:5432/cik" }
      - run: scripts/self_test_fast.sh

  dashboard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: npm, cache-dependency-path: dashboard/package-lock.json }
      - run: npm ci --prefix dashboard
      - run: npm run lint --prefix dashboard
      - run: npm test --prefix dashboard -- --runInBand
      - run: npm run build --prefix dashboard   # catches type + build errors
        env: { NEXT_PUBLIC_API_URL: "https://api.example.com" }

  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@master     # container + FS vuln scan
      - run: pip install pip-audit && pip-audit    # Python dep CVEs
      - run: npm audit --prefix dashboard --audit-level=high
```

- **Deploy**: `.github/workflows/deploy.yml` triggered on `v*` tags or a manual
  `workflow_dispatch` with an environment selector:
  `build images → run scripts/self_test_fast.sh → push to registry → ssh to VPS → docker compose pull + up -d → scripts/smoke_test.sh`.
- CI **secrets** (repo settings): `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`,
  `CIK_SECRET_KEY`, `SENTRY_DSN`, `RESEND_API_KEY`.

### A2: Compose hardening — `docker-compose.prod.yml` v2
**Effort:** 0.5 days
**Deliverable:** updated `docker-compose.prod.yml`

- Pin image tags (no `latest`), set `restart: unless-stopped` (already there),
  add `read_only: true` where feasible, cap worker concurrency, set
  `--workers 4` for uvicorn (via an `API_WORKERS` env default 4), and tune
  `pool_size` via env.
- Non-root runtime: the API image should run as `appuser` (Dockerfile `USER`).
- Healthcheck intervals tuned; `depends_on` already uses `service_healthy`.

---

## Track B: Deploy + TLS + Observability

### B1: Caddy reverse proxy — `caddy/Caddyfile`
**Effort:** 0.5 days
**Deliverable:** `caddy/Caddyfile`, compose service

```
api.example.com   { reverse_proxy api:8000 }
dashboard.example.com  { reverse_proxy dashboard:3000 }
```

- Caddy provisions + renews Let's Encrypt automatically; `docs/DEPLOYMENT.md`
  already documents this. Add the `caddy` service to the prod overlay.
- `CORS_ORIGINS=https://dashboard.example.com`,
  `NEXT_PUBLIC_API_URL=https://api.example.com` in the production `.env`.

### B2: Backups + retention — `scripts/backup.sh`
**Effort:** 1 day
**Deliverable:** `scripts/backup.sh` + `docs/BACKUPS.md`

```bash
#!/usr/bin/env bash
# Nightly: pg_dump → encrypt (age/gpg) → push to S3-compatible storage → prune.
# Env: PG_DUMP_URL, BACKUP_BUCKET, BACKUP_ENCRYPTION_KEY (or path to age key),
#      BACKUP_RETENTION_DAYS (default 14).
```

- Steps: `pg_dump -Fc` → `age -r <key> -o` → `aws s3 cp` (or `rclone`) →
  list + delete objects older than retention.
- **Restore drill** (documented in `docs/BACKUPS.md`): `age -d` → `pg_restore`
  into a scratch database → verify row counts → swap.
- Add a `backup` service to compose (or a cron on the VPS) running the script
  nightly at 02:00 UTC; the admin `/metrics` shows last-backup timestamp.

### B3: Observability — Sentry + uptime + logs
**Effort:** 1 day
**Deliverable:** `docs/MONITORING.md`, alert rules, optional Prometheus/Grafana

- **Sentry** (already wired in `api/app.py:34`): enable alerts on
  `UnhandledError`, `PipelineJobFailed`, `SourceDrift`, `AnomalyDetected`
  (the tags added in Sprint 09). Add the dashboard's client-side Sentry
  (`@sentry/nextjs`) with `tracesSampleRate: 0.1`.
- **Uptime**: external checks (UptimeRobot/Healthchecks.io) hitting `/health`
  and `/ready` every minute; notify on first failure and recovery.
- **Logs**: structure the API logs to JSON (`python-json-logger`) with a
  `request_id` middleware; collect via the platform's log UI or a simple
  `docker compose logs` in emergencies. `docs/MONITORING.md` documents the
  alert → triage runbook.

---

## Track C: Load Test + Performance Tuning

### C1: Locust load test — `loadtest/locustfile.py`
**Effort:** 1 day
**Deliverable:** `loadtest/locustfile.py` + `docs/LOAD_TESTING.md`

```python
# loadtest/locustfile.py — simulate a realistic user: register/login/build
# profile/list matches/bookmark. Target: 1000 concurrent users at launch cap.
from locust import HttpUser, task, between

class Researcher(HttpUser):
    wait_time = between(5, 20)      # human-paced, not hammering
    @task(3) def list_matches(self): self.client.get("/api/v1/matches")
    @task(2) def list_opportunities(self): self.client.get("/api/v1/opportunities")
    @task(1) def view_profile(self): self.client.get("/api/v1/me")
    @task(1) def bookmark(self): ... # authenticated path
```

- Run: `docker compose -f loadtest/... up` against the staging deploy (never
  production), or `locust -f loadtest/locustfile.py --headless -u 1000 -r 50`.
- **Success criteria** (see `docs/LOAD_TESTING.md`): p95 < 500 ms for reads,
  error rate < 1%, no 5xx storm, DB pool not exhausted (watch
  `/api/admin/pool-status`).

### C2: Performance tuning from results
**Effort:** 1 day
**Deliverable:** index/migration additions + tuned pool/cache

- Add DB indexes the load test surfaces as hot (query planner review of the
  slowest endpoints: `matches`, `opportunities` filters).
- Tune `pool_size`/`max_overflow` (from 5/10 → e.g. 10/20) and cache TTLs
  based on measured hit rates.
- Re-run `scripts/self_test.sh` after any tuning — behavior must not change.

---

## Track D: Security Audit + Compliance

### D1: Security audit checklist — `docs/SECURITY.md`
**Effort:** 1 day
**Deliverable:** `docs/SECURITY.md` + fixes

Walk and document every item:

| Area | Check | Status (verify) |
|------|-------|-----------------|
| Secrets | No secrets in repo/CI logs; `CIK_SECRET_KEY` is 32+ random bytes; key rotation documented | |
| Auth | bcrypt cost ≥ 12; JWT 1 h expiry; Redis rate limits on register/login/reset; lockout | |
| Transport | TLS only (Caddy); HSTS header present (already in `api/app.py:105`) | |
| Input | Pydantic validation everywhere; SSRF guard on crawled/seed URLs (no private IP/loopback) | |
| Dependencies | `pip-audit`, `npm audit`, Trivy clean on CI (Track A) | |
| Data | PII only where needed; profile raw_text is user-controlled; email bounces handled | |
| API keys | Only SHA-256 stored; revoked keys rejected (Sprint 08) | |
| Rate limits | Global IP caps + per-user + per-key (Sprint 07/08) | |
| Backups | Encrypted at rest; retention; restore tested (B2) | |
| OWASP | Run the OWASP Top 10 checklist against the app | |

- **SSRF guard** (the one item needing code): in `core/http.py` / seed-url
  handling, block URLs resolving to loopback/private/link-local IPs before
  fetching. This is the highest-risk gap for a crawler-backed platform.

### D2: GDPR / privacy — legal pages + data endpoints
**Effort:** 1 day
**Deliverable:** `dashboard/app/{privacy,terms,about}/page.tsx`, API endpoints

- Static pages: Privacy Policy, Terms of Service, About (in the dashboard's
  public, non-auth section — currently everything is behind `AuthGate`; add a
  public route group).
- **Data subject endpoints** (required for EU users at public launch):
  - `GET /api/account/data-export` → JSON of the user's profile, bookmarks,
    matches, feedback, audit trail.
  - `DELETE /api/account` → GDPR erase: delete profile + PII, anonymize audit
    rows, revoke keys (soft-delete matches/feedback to preserve analytics
    aggregates).
  - `GET /api/account/consent` + `PUT /api/account/consent` → marketing-email
    consent toggle (ties into the digest preference).
- Cookie banner component (functional cookies only; document it in Privacy).

### D3: Landing page + docs polish
**Effort:** 1 day
**Deliverable:** `dashboard/app/landing/page.tsx` (or the root when
unauthenticated), `docs/GETTING_STARTED.md` update

- Public landing: value proposition, how it works (3 steps), privacy line,
  CTA → register (invite-gated).
- Update `GETTING_STARTED.md` + `DEVELOPER_API.md` with the production URLs.

---

## Track E: Launch Go/No-Go Checklist

### E1: `docs/LAUNCH_CHECKLIST.md`
**Effort:** 0.5 days
**Deliverable:** `docs/LAUNCH_CHECKLIST.md`

A single sign-off document covering (each must be checked before opening
public registration):

- [ ] `scripts/self_test.sh` green on `main`
- [ ] Smoke test passes against the production compose stack
- [ ] Sentry DSN live; alerts firing (test with a forced error)
- [ ] Uptime checks on `/health` + `/ready`; on-call/notification configured
- [ ] Nightly backup ran; a restore drill succeeded within the last 7 days
- [ ] Load test at 1000 users met the success criteria
- [ ] `pip-audit`/`npm audit`/Trivy clean; OWASP checklist complete; SSRF guard shipped
- [ ] Privacy/Terms live; data-export + delete endpoints tested
- [ ] `INVITES_REQUIRED=1` in production (registration gated until go)
- [ ] `CIK_SECRET_KEY` rotated; `.env` matches `.env.example`
- [ ] `CORS_ORIGINS` points at the real dashboard origin; HSTS verified
- [ ] Resend domain verified; bounce webhook live; unsubscribe tested
- [ ] Postgres + Redis running with the prod profile; pool tuned
- [ ] 1000-user capacity: `API_WORKERS`, `pool_size`, cache verified under load

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (CI/CD) | PRs run backend + dashboard + security jobs; tag triggers a deploy + smoke test |
| A2 (Compose prod) | Prod overlay is non-root, pinned, healthchecked, worker-capped |
| B1 (Caddy) | TLS auto-provisions for both hosts; CORS/API URL point at prod |
| B2 (Backups) | Nightly encrypted pg_dump to object storage; restore drill documented + run once |
| B3 (Observability) | Sentry + uptime + JSON logs + monitoring runbook |
| C1 (Load test) | 1000-user scenario in repo; success criteria defined in LOAD_TESTING.md |
| C2 (Tuning) | Hot-path indexes + pool tuned from results; self-test still green |
| D1 (Security) | SECURITY.md complete; SSRF guard shipped; scans clean |
| D2 (GDPR) | Privacy/Terms live; data-export + delete + consent endpoints tested |
| D3 (Landing) | Public landing + docs updated with prod URLs |
| E1 (Checklist) | LAUNCH_CHECKLIST.md exists and each item verified |
| **Regression** | All existing tests still pass |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| CI green but prod broken | Every deploy runs the smoke test; staging-first deploy flow |
| Backup restore never tested | Scheduled restore drill; documented procedure |
| 1000 users exceed a single VPS | Load test first; keep Postgres/Redis on the same box but tune; scale-out path documented (move PG/Redis to managed) |
| TLS misconfig kills the auth cookie | Cookie is Secure+SameSite=Strict; smoke test verifies a full auth flow over https |
| SSRF through seed URLs | Block private/loopback/link-local IP resolution before fetch |
| GDPR delete removes analytics | Anonymize rather than hard-delete feedback/matches; document policy |
| New team member breaks something | All 4 gates (self-test, pytest, npm test, build) enforced in CI |
| LLM bill at public launch | Monthly cap + feature toggles shipped in Sprint 09, verified in checklist |

---

## Sprint 10 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_10.md
2. /home/mohammad-reza/career_intelligence_kit/docker-compose.yml
3. /home/mohammad-reza/career_intelligence_kit/docker-compose.prod.yml
4. /home/mohammad-reza/career_intelligence_kit/docs/DEPLOYMENT.md
5. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/core/http.py

Then execute Sprint 10 from SPRINT_10.md, in this order:

TRACK A — CI/CD:

A1. Create .github/workflows/ci.yml — backend job (self-test + pytest against postgres + redis services, self_test_fast.sh), dashboard job (npm ci/lint/test/build), security-scan job (trivy, pip-audit, npm audit). Create .github/workflows/deploy.yml — on v* tag: build images → self_test_fast.sh → push → ssh deploy → smoke_test.sh.
A2. Harden docker-compose.prod.yml — pinned tags, read_only where feasible, API_WORKERS env (default 4), pool_size env, non-root USER in the API Dockerfile.

TRACK B — DEPLOY + TLS + OBSERVABILITY:

B1. Create caddy/Caddyfile (api + dashboard hosts, automatic TLS) and add a caddy service to the prod overlay. Set prod CORS_ORIGINS + NEXT_PUBLIC_API_URL.
B2. Create scripts/backup.sh (pg_dump -Fc → age/gpg encrypt → s3/rclone upload → prune to BACKUP_RETENTION_DAYS) and docs/BACKUPS.md with a restore drill. Add a compose backup service (nightly 02:00 UTC).
B3. Create docs/MONITORING.md — Sentry alert rules (UnhandledError, PipelineJobFailed, SourceDrift, AnomalyDetected), uptime checks on /health + /ready, JSON logging + request_id middleware, runbook.

TRACK C — LOAD TEST + TUNING:

C1. Create loadtest/locustfile.py (register/login/build profile/list matches/bookmark; 1000 users, human-paced wait_time) and docs/LOAD_TESTING.md (how to run, success criteria: p95<500ms reads, error rate<1%, pool not exhausted).
C2. Tune from results: add the hot-path DB indexes, adjust pool_size/max_overflow (10/20) and cache TTLs. Re-run scripts/self_test.sh to confirm no behavior change.

TRACK D — SECURITY + COMPLIANCE:

D1. Create docs/SECURITY.md — complete the checklist in the sprint, run the OWASP Top 10 review, and SHIP THE SSRF GUARD: block URLs resolving to loopback/private/link-local IPs before any fetch in core/http.py (and in seed_urls handling).
D2. Create dashboard/app/privacy/page.tsx, dashboard/app/terms/page.tsx, dashboard/app/about/page.tsx as a public (non-auth) route group. Add API endpoints: GET /api/account/data-export, DELETE /api/account (GDPR erase), GET+PUT /api/account/consent. Cookie banner component. Tests for all three endpoints.
D3. Create the public landing page (value prop, 3 steps, CTA) and update GETTING_STARTED.md + DEVELOPER_API.md with prod URLs.

TRACK E — GO/NO-GO:

E1. Create docs/LAUNCH_CHECKLIST.md with every item from the sprint table and mark progress. Verify each reachable item now.

RULES:
- Never deploy to production from this session without explicit approval.
- All 4 gates stay green: scripts/self_test.sh, pytest, npm test, npm run build.
- GDPR delete anonymizes (not hard-deletes) feedback/matches; document it.
- SSRF guard is mandatory — do not ship D1 without it.
- The CLI and existing API endpoints must not change behavior.
```
