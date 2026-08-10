# Sprint 06: Production Hardening + Private Beta Prep

**Duration:** Weeks 12-14 (2026-08-04 → 2026-08-25)
**Goal:** Harden for production deployment, prepare for private beta with 10-20 users

---

## What shipped in Sprints 01-05 (for context)

| Item | Status |
|------|--------|
| Full backend (CLI + API + matching + profile + DB) | DONE |
| Dashboard (6 pages, responsive, auth-gated) | DONE |
| Docker (API + dashboard containers) | DONE |
| Security (JWT, bcrypt, rate limiting, CORS, headers) | DONE |
| Tests: 419 passing | DONE |

---

## Track A: Database + PostgreSQL (Week 12)

### A1: PostgreSQL support
**Effort:** 1 day
**Deliverable:** Update `db/init.py`, `api/deps.py`

- Support both SQLite and PostgreSQL via `DATABASE_URL` env var
- Add `psycopg2-binary` to requirements
- Update `docker-compose.yml` with optional PostgreSQL service
- Test: run API tests against both SQLite and PostgreSQL

### A2: Database migrations (Alembic)
**Effort:** 1 day
**Deliverable:** `alembic/` directory, `alembic.ini`

```bash
pip install alembic
alembic init alembic
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- Generate initial migration from existing models
- Test: `alembic upgrade head` creates all tables
- Test: `alembic downgrade` rolls back cleanly

### A3: Connection pooling
**Effort:** 0.5 days
**Deliverable:** Update `api/deps.py`

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
)
```

- Configure pool size based on expected concurrent users
- Add pool status endpoint: `GET /api/admin/pool-status`

---

## Track B: Caching + Background Jobs (Week 13)

### B1: Redis caching layer
**Effort:** 1 day
**Deliverable:** `core/cache.py`

```python
import redis

redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))

def cache_match_results(profile_id: int, results: list) -> None:
    key = f"matches:{profile_id}"
    redis_client.setex(key, 3600, json.dumps(results))  # 1 hour TTL

def get_cached_matches(profile_id: int) -> Optional[list]:
    key = f"matches:{profile_id}"
    data = redis_client.get(key)
    return json.loads(data) if data else None
```

- Cache match results (deterministic = safe to cache)
- Cache opportunity list (invalidate on new pipeline run)
- Cache supervisor list (invalidate on new data)

### B2: Background job queue
**Effort:** 1 day
**Deliverable:** `core/tasks.py`, update `api/routes/pipeline.py`

Replace threading with a proper job queue:
- Option 1: `rq` (Redis Queue) — simpler, good for MVP
- Option 2: `celery` — more features, heavier

Recommendation: Start with `rq` for simplicity.

```python
from rq import Queue
from redis import Redis

redis_conn = Redis()
q = Queue(connection=redis_conn)

def run_pipeline_job(run_id: str, sources: list, country: str):
    """Background job that runs the pipeline."""
    # ... existing pipeline logic ...

# In API endpoint:
job = q.enqueue(run_pipeline_job, run_id, sources, country)
```

- Add `rq-dashboard` for monitoring jobs
- Add job status endpoint: `GET /api/jobs/{job_id}`
- Add job cancellation: `DELETE /api/jobs/{job_id}`

### B3: Error tracking (Sentry)
**Effort:** 0.5 days
**Deliverable:** Update `api/app.py`

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.1,  # 10% of requests
)
```

- Add `SENTRY_DSN` to `.env.example`
- Configure release tracking
- Add user context for authenticated requests

---

## Track C: Private Beta (Week 14)

### C1: Beta invite system
**Effort:** 1 day
**Deliverable:** `api/routes/invites.py`, `db/models.py` update

Add `Invite` model:
```python
class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
```

Endpoints:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/invites` | POST | Create invite (admin only) |
| `/api/invites` | GET | List invites (admin only) |
| `/api/invites/{code}/redeem` | POST | Redeem invite during registration |

- Registration requires valid invite code
- Admin can create invites (bootstrap first admin via CLI)
- Track invite usage for analytics

### C2: User onboarding flow
**Effort:** 1 day
**Deliverable:** `dashboard/app/onboarding/page.tsx`

Step-by-step wizard:
1. Welcome screen
2. Paste CV/bio text
3. Review extracted profile
4. Select field profile
5. Set country preferences
6. Done → redirect to dashboard

- Store onboarding progress in localStorage
- Skip if profile already exists
- Show progress indicator

### C3: Feedback collection
**Effort:** 0.5 days
**Deliverable:** Update `dashboard/components/MatchCard.tsx`

Add thumbs up/down buttons to each match card:
- Thumbs up: "This match is relevant"
- Thumbs down: "This match is not relevant" + optional comment
- Store via `POST /api/matches/{id}/feedback`
- Show feedback count on admin dashboard

### C4: Monitoring dashboard (admin)
**Effort:** 1 day
**Deliverable:** `dashboard/app/admin/page.tsx`

Admin-only page showing:
- Source health (last run time, record count, errors)
- API metrics (request count, latency, error rate)
- User metrics (total users, active users, profiles built)
- Job queue status (pending, running, completed, failed)
- Invite usage (created, redeemed, pending)

- Protect with admin role check
- Refresh every 30 seconds

---

## Track D: Documentation (Week 14, parallel)

### D1: Getting started guide
**Effort:** 0.5 days
**Deliverable:** `docs/GETTING_STARTED.md`

- Prerequisites (Python 3.10+, Docker, API keys)
- Quick start (docker-compose up)
- First-time setup (register, build profile, see matches)
- CLI usage (alternative to dashboard)

### D2: API documentation
**Effort:** 0.5 days
**Deliverable:** Update `docs/API.md`

- All 18+ endpoints documented
- Authentication flow
- Request/response examples
- Error codes
- Rate limiting headers

### D3: Deployment guide
**Effort:** 0.5 days
**Deliverable:** `docs/DEPLOYMENT.md`

- Docker deployment (docker-compose)
- Manual deployment (systemd services)
- PostgreSQL setup
- Redis setup
- Environment variables reference
- SSL/TLS configuration

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (PostgreSQL) | API tests pass against PostgreSQL |
| A2 (Alembic) | `alembic upgrade head` creates schema, `downgrade` rolls back |
| A3 (Connection pooling) | Pool status endpoint returns metrics |
| B1 (Redis caching) | Match results cached, invalidated on new data |
| B2 (Job queue) | Pipeline runs in background worker, status tracked |
| B3 (Sentry) | Errors tracked, user context attached |
| C1 (Invites) | Admin creates invite, user redeems during registration |
| C2 (Onboarding) | Step-by-step wizard completes profile setup |
| C3 (Feedback) | Thumbs up/down stored, visible in admin |
| C4 (Admin dashboard) | Metrics displayed, auto-refreshing |
| D1-D3 (Docs) | Getting started, API, deployment guides complete |

---

## Sprint 06 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_06.md
2. /home/mohammad-reza/career_intelligence_kit/db/models.py
3. /home/mohammad-reza/career_intelligence_kit/api/deps.py
4. /home/mohammad-reza/career_intelligence_kit/docker-compose.yml

Then execute Sprint 06 from SPRINT_06.md, in this order:

TRACK A — DATABASE:

A1. Add PostgreSQL support: add psycopg2-binary to requirements.txt. Update db/init.py to accept DATABASE_URL env var (sqlite or postgresql). Update docker-compose.yml with optional postgres service. Test: run tests with both SQLite and PostgreSQL.

A2. Set up Alembic: `pip install alembic && alembic init alembic`. Configure alembic.ini for both SQLite and PostgreSQL. Generate initial migration from existing models. Test: `alembic upgrade head` creates all tables, `alembic downgrade` rolls back.

A3. Add connection pooling: Update api/deps.py to use QueuePool with pool_size=5, max_overflow=10. Add GET /api/admin/pool-status endpoint.

TRACK B — CACHING + JOBS:

B1. Create core/cache.py with Redis client. Cache match results (1 hour TTL). Cache opportunity list (invalidate on pipeline run). Cache supervisor list (invalidate on new data). Add REDIS_URL to .env.example.

B2. Install rq (Redis Queue). Create core/tasks.py with run_pipeline_job function. Update api/routes/pipeline.py to use rq instead of threading. Add GET /api/jobs/{job_id} for status, DELETE /api/jobs/{job_id} for cancellation. Add rq-dashboard for monitoring.

B3. Add Sentry: pip install sentry-sdk[fastapi]. Initialize in api/app.py with SENTRY_DSN env var. Add user context for authenticated requests.

TRACK C — PRIVATE BETA:

C1. Add Invite model to db/models.py (code, created_by, used_by, timestamps). Create api/routes/invites.py with POST /api/invites (create), GET /api/invites (list), POST /api/invites/{code}/redeem (redeem). Update registration to require invite code. Add admin role to User model.

C2. Create dashboard/app/onboarding/page.tsx — Step-by-step wizard: welcome → paste CV → review profile → select field → set countries → done. Store progress in localStorage. Skip if profile exists.

C3. Update dashboard/components/MatchCard.tsx — Add thumbs up/down buttons. Call POST /api/matches/{id}/feedback on click. Show feedback count.

C4. Create dashboard/app/admin/page.tsx — Admin dashboard: source health, API metrics, user metrics, job queue status, invite usage. Protect with admin role. Auto-refresh every 30s.

TRACK D — DOCUMENTATION:

D1. Create docs/GETTING_STARTED.md — Prerequisites, quick start, first-time setup, CLI usage.

D2. Update docs/API.md — All endpoints documented with examples.

D3. Create docs/DEPLOYMENT.md — Docker, manual, PostgreSQL, Redis, env vars, SSL.

RULES:
- All existing tests must pass after every change.
- PostgreSQL tests run in CI (docker-compose with postgres service).
- Redis is optional (graceful fallback to in-memory cache when unavailable).
- Invite system is opt-in (registration works without invites in dev mode).
- Admin role is only for the first user (bootstrapped via CLI).
- Documentation must be accurate and tested.
```
