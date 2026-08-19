# Deployment Guide

Production deployment options for the Astra: Docker Compose
(recommended), or manual systemd services. Covers PostgreSQL, Redis, the rq
worker, environment variables, and SSL/TLS.

---

## Architecture

```
                    ┌──────────────┐
  Browser ────────► │  dashboard   │  Next.js (3000)
                    └──────┬───────┘
                           │ NEXT_PUBLIC_API_URL
                    ┌──────▼───────┐
                    │     api      │  FastAPI/uvicorn (8000)
                    └──┬─────┬──┬──┘
                       │     │  └──── rq worker ◄─ Redis
              ┌────────▼──┐  └──────── Redis (cache + queue)
              │ PostgreSQL│  (or SQLite file — dev)
              └───────────┘
```

- **API** — FastAPI behind uvicorn; single process or horizontal workers behind
  a reverse proxy.
- **Dashboard** — static Next.js build serving the SPA.
- **PostgreSQL** — optional `DATABASE_URL` backend (SQLite is the dev default).
- **Redis** — optional; powers the result **cache** (`core/cache.py`) and the
  **rq job queue** (`core/tasks.py`). When absent, both fall back to
  in-process equivalents (dev/test safe).
- **Worker** — one or more `rq worker default` processes that execute pipeline
  runs.

---

## 1. Docker Compose (recommended)

`.env.example` → copy to `.env` and fill in.

```bash
cp .env.example .env
```

### Minimal (SQLite + in-memory cache, no Redis/PG)

```bash
docker compose up -d --build
```

### Production profile (PostgreSQL + Redis + worker)

```bash
docker compose --profile redis --profile postgres up -d --build
```

The `redis` profile brings up the Redis container **and** the `worker`
service; `postgres` adds the database. To route the API at PostgreSQL, set in
`.env`:

```dotenv
DATABASE_URL=postgresql://astra:CHANGE_ME@postgres:5432/astra
```

### Run migrations

```bash
docker compose exec api alembic upgrade head
```

### Hardening overlay

`docker-compose.prod.yml` enforces secrets and removes host port exposure
(everything behind a reverse proxy):

```bash
docker compose \
  --profile redis --profile postgres \
  -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --build
```

For a full engineer-architected beta deployment see the ops docs:

- `PROVISIONING.md` — harden the OS, wire up TLS, first-run admin/invites.
- `BETA_RUNBOOK.md` — invites, day-to-day health, upgrades, incident playbooks.
- `BETA_CHECKLIST.md` — the go/no-go list to walk before opening the beta.
- `BACKUPS.md` — nightly encrypted backups and restore drills.
- `SECURITY.md` — the security posture checklist; `MONITORING.md` — Sentry,
  uptime, JSON logs, alert triage.

---

## 2. Reverse proxy + SSL/TLS

Terminate TLS in front of the API with Caddy, Nginx, or Traefik. Caddy example
(`caddy/`):

```
api.example.com {
    reverse_proxy api:8000
}
dashboard.example.com {
    reverse_proxy dashboard:3000
}
```

Then in `.env`:

```dotenv
CORS_ORIGINS=https://dashboard.example.com
NEXT_PUBLIC_API_URL=https://api.example.com
```

The API already sends security headers (HSTS, `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`). The auth cookie is `Secure` and
`SameSite=Strict`, so the dashboard and API must be served over HTTPS with the
API origin in `CORS_ORIGINS`.

---

## 3. Manual deployment (systemd)

### 3.1 API unit — `/etc/systemd/system/astra-api.service`

```ini
[Unit]
Description=Astra API
After=network.target

[Service]
User=astra
WorkingDirectory=/opt/astra/astra
EnvironmentFile=/etc/astra/astra.env
ExecStart=/opt/astra/astra/.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3.2 Worker unit — `/etc/systemd/system/astra-worker.service`

```ini
[Unit]
Description=Astra rq worker
After=network.target

[Service]
User=astra
WorkingDirectory=/opt/astra/astra
EnvironmentFile=/etc/astra/astra.env
ExecStart=/opt/astra/astra/.venv/bin/rq worker default
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now astra-api astra-worker
```

`/etc/astra/astra.env` holds the same vars as `.env` (plus `REDIS_URL`,
`DATABASE_URL`, `ASTRA_SECRET_KEY`).

### 3.3 Dashboard

Build once and serve as static files (or run `npm start` behind the proxy):

```bash
cd dashboard
NEXT_PUBLIC_API_URL=https://api.example.com npm run build
# serve .next standalone / `npm start` behind nginx/Caddy
```

---

## 4. PostgreSQL

Set `DATABASE_URL=postgresql://user:pass@host:5432/db`. The API configures a
bounded `QueuePool` automatically:

- `pool_size=5`, `max_overflow=10`, `pool_timeout=30s`, `pool_recycle=1800s`

Verify with `GET /api/admin/pool-status` (admin). Create the database:

```bash
createdb astra
psql astra -c "CREATE USER astra WITH PASSWORD 'CHANGE_ME';"
psql astra -c "GRANT ALL PRIVILEGES ON DATABASE astra TO astra;"
```

### Migrations (Alembic)

```bash
cd astra
alembic upgrade head      # apply all migrations
alembic revision --autogenerate -m "describe change"   # after model edits
alembic downgrade -1      # roll back one step
```

Migrations directory: `astra/alembic/`. The initial migration creates
all tables; a second adds the user `role` column.

---

## 5. Redis

If you enable `REDIS_URL`, start Redis and the worker:

```bash
# general
redis-server
rq worker default

# Docker (from the compose profiles):
docker compose --profile redis up -d
```

Without Redis everything still works: `core/cache.py` falls back to an
in-memory cache and `core/tasks.py` runs jobs in-process. Redis adds:

- shared cache across API workers (1 h TTLs)
- a durable job queue with retries/TTL and a separate worker
- `rq-dashboard` for monitoring (pip-installed; run `rq-dashboard`)

---

## 6. Environment variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| **App / security** | | |
| `ASTRA_SECRET_KEY` | *(dev, insecure)* | JWT signing key. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | `*` (dev) | Comma-separated allowed origins; enables the auth cookie |
| `SENTRY_DSN` | *(off)* | Sentry error tracking DSN |
| `INVITES_REQUIRED` | *(off)* | `1`/`true` → registration requires an invite code |
| `RESEND_API_KEY` | *(off → dev mode)* | Resend key; unset = email sends are logged, not sent |
| `RESEND_WEBHOOK_SECRET` | *(off → no verify)* | Verifies Resend webhook signatures |
| `EMAIL_FROM` | `Astra <no-reply@example.com>` | From-address for sent emails |
| `DASHBOARD_URL` | `https://dashboard.example.com` | Public dashboard origin (digest links, reset links) |
| **Database** | | |
| `DATABASE_URL` | `sqlite:///astra.db` | SQLAlchemy URL (SQLite or PostgreSQL) |
| **Cache + jobs** | | |
| `REDIS_URL` | *(unset → in-memory)* | Redis URL for cache + rq queue |
| **LLM** | | |
| `LLM_DEFAULT_MODEL` | litellm default | Primary model id, e.g. `gpt-4o-mini` |
| `LLM_FALLBACK_MODEL` | litellm default | Fallback, e.g. `ollama/llama3.1:8b` |
| `OPENAI_API_KEY` | | OpenAI provider key |
| `OLLAMA_HOST` | | Local Ollama endpoint |
| **Sources** | | |
| `ADS_API_TOKEN` | | NASA ADS API token |
| `OPENALEX_MAILTO` | | Email for OpenAlex polite pool |
| **Dashboard** | | |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Browser-side base URL to the API |

---

## 7. Health, readiness, operations

- `GET /health` — always 200 when the process is alive.
- `GET /ready` — 200 when the DB is reachable, 503 otherwise; reports LLM
  availability.
- `GET /api/admin/pool-status` — DB pool health (admin).
- `GET /api/admin/metrics` — users, content, API request stats, job queue and
  invite usage (admin); the dashboard tab auto-refreshes every 30 s.
- `GET /api/admin/audit` — audit trail (admin): register/login/reset/verify/
  unsubscribe/invite/admin actions (Sprint 07, B4).

---

## 7.1 Weekly email digest (Sprint 07, A3)

The weekly digest is enqueued on **Monday 08:00 UTC** for every profile whose
`DigestPreference.frequency = 'weekly'`:

- **With Redis:** `rq-scheduler` (installed with `pip install rq-scheduler`)
  runs the `0 8 * * 1` cron. Start it alongside the worker in the compose
  `worker` service: `rqscheduler --host <redis> --port 6379 --db 0 --verbose`.
- **Without Redis (fallback):** `api.app` starts a `threading.Timer` daily
  check (`core.tasks.start_digest_scheduler`) that fires any missed weekly run
  and reschedules itself — so weekly digests still go out on a single API
  process with no extra service.

Both paths call `send_digest_job` for each profile, which builds a deterministic
digest (score > 0.85, max 5 positions / 5 supervisors), sends via Resend, and
records an `email_events` row. Sends are always off the request path.

---

## 8. Backups

- **PostgreSQL:** `pg_dump astra > astra-$(date +%F).sql` regularly; or snapshot the
  `astra-pgdata` volume.
- **SQLite:** stop writes, then copy `astra.db` (or use the SQLite backup
  API).

---

## 9. Running migrations / database at deploy time

```bash
# after pulling new code:
alembic upgrade head
# first admin + seed:
python astra.py --db "$DATABASE_URL" --make-admin you@example.com
python astra.py --db "$DATABASE_URL" --seed-db astra_positions.json
```