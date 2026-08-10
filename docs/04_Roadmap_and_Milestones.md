# Roadmap and Milestones

Last updated: 2026-08-08

## Current Status

- **Modular codebase:** 521-line CLI + 100 Python files across 10 packages
- **Migration:** Steps 1-12 **COMPLETE**
- **Profile engine:** Built + wired to CLI + API
- **Database:** 9 tables + Alembic migrations + PostgreSQL support
- **Matching engine:** 3 dimensions + explainability, deterministic, cached (Redis)
- **REST API:** FastAPI with 18+ internal endpoints + public `/api/v1` developer API, auth, rate limiting, CORS, security headers
- **Public developer API (Sprint 08):** scoped API keys (`cik_`), rate limits, daily quotas, rotation/revocation, admin management, dashboard keys page — see `docs/DEVELOPER_API.md`
- **Dashboard:** 9 pages (matches, profile, supervisors, bookmarks, settings, opportunities, onboarding, admin, API keys)
- **Infrastructure:** Docker, PostgreSQL, Redis, Alembic, Sentry, RQ job queue, connection pooling
- **Private beta:** Invite system, onboarding wizard, feedback collection, admin monitoring
- **Documentation:** GETTING_STARTED.md, API.md, DEVELOPER_API.md, DEPLOYMENT.md
- **Tests:** 561 backend + 53 dashboard passing

---

## Month 1 — Foundation (Weeks 1-7) — **COMPLETE**

### Phase 1: Monolith Refactor — **DONE**

| Step | What | Status |
|------|------|--------|
| 1 | Extract `core/config.py` | DONE |
| 2 | Extract `core/utils.py` + `core/records.py` | DONE |
| 3 | Extract `core/taxonomy.py` | DONE |
| 4 | Extract `core/http.py` | DONE |
| 5 | Move sources to `sources/` | DONE |
| 6 | Extract `pipeline/parse_page.py` | DONE |
| 7 | Extract `pipeline/filter.py` + `dedupe.py` + `freshness.py` | DONE |
| 8 | Extract `pipeline/run.py` | DONE |
| 9 | Extract `supervisors/` | DONE |
| 10 | Extract `toolkit/` | DONE |
| 11 | Slim `phd_aggregator.py` to CLI entry point | DONE |
| 12 | Full test suite | DONE |

### Phase 2: Structured User Profile — **DONE**

| Task | Status |
|------|--------|
| LLM provider evaluation | **DONE** (LiteLLM + OpenAI + Ollama) |
| `UserProfile` Pydantic schema | **DONE** |
| LLM wrapper (`core/llm.py`) | **DONE** |
| Profile extraction (`core/profile.py`) | **DONE** |
| CLI integration (`--build-profile`) | **DONE** |
| Profile → DB persistence | **DONE** |

### Phase 3: Opportunity Database — **DONE**

| Task | Status |
|------|--------|
| ER diagram + schema spec | **DONE** |
| SQLAlchemy models (7 tables) | **DONE** |
| Seed from JSON output | **DONE** |
| Repository pattern | **DONE** |
| Pipeline → DB wiring | **DONE** |
| `--seed-db` CLI | **DONE** |

### Phase 4: Deterministic Matching Engine — **DONE**

| Task | Status |
|------|--------|
| 3-dimension scoring (topic, method, location) | **DONE** |
| Explainability generator | **DONE** |
| Golden-set test suite | **DONE** (303 tests) |
| Pipeline integration (`--run` with profile) | **DONE** |

### Phase 5: CLI Integration — **DONE**

| Task | Status |
|------|--------|
| `--build-profile "CV text"` | **DONE** |
| `--seed-db path` | **DONE** |
| `--show-profile` | **DONE** |
| `--run` with active profile → match scores | **DONE** |

---

## Month 2 — Web API + Dashboard (Weeks 8-11) — **COMPLETE**

### Phase 6: FastAPI REST API — **DONE**

18 endpoints, auth, rate limiting, CORS, security headers, match caching, pipeline concurrency. 87 API tests.

### Phase 7: Dashboard UI — **DONE**

| Page | Status |
|------|--------|
| Onboarding (CV paste → build profile) | DONE |
| Dashboard (match cards + filters) | DONE |
| Profile view/edit | DONE |
| Supervisor view (search, filter, ORCID) | DONE |
| Bookmarks page (list, delete, confirm) | DONE |
| Settings (field profile, notifications) | DONE |
| Opportunities (filters, pagination) | DONE |

### Phase 8: Auth + Multi-user — **DONE**

bcrypt + JWT + httpOnly cookie, rate limiting, user-scoped data, thread-safe engine.

### Docker + Production — **DONE**

API + dashboard containers, healthchecks, env config, secrets enforcement, security headers.

---

## Month 3 — Production Hardening + Private Beta Prep (Weeks 12-14) — **COMPLETE**

Goal: Harden for production, prepare for private beta with 10-20 users.

### Production hardening — **DONE**
- PostgreSQL option (via DATABASE_URL env var)
- Redis caching (with in-memory fallback)
- Sentry error tracking
- Security headers (HSTS, X-Frame-Options, X-Content-Type-Options)

### Performance + reliability — **DONE**
- Database connection pooling (SQLAlchemy QueuePool)
- API response caching (Redis or in-memory)
- Background job queue (RQ with thread fallback)
- Database migrations (Alembic with 3 migrations)

### Private beta preparation — **DONE**
- Beta invite system (admin creates codes, users redeem)
- User onboarding flow (6-step wizard)
- Feedback collection (thumbs up/down on matches)
- Admin dashboard (source health, API metrics, user metrics, job queue)
- Documentation (GETTING_STARTED.md, API.md, DEPLOYMENT.md)

---

## Month 4 — Private Beta (Weeks 15-18)

Goal: Deploy to production, invite 10-20 beta users, collect feedback.

### Deployment (Week 15)
- Deploy to VPS or cloud (DigitalOcean, Railway, or similar)
- Configure SSL/TLS (Let's Encrypt or cloud provider)
- Set up monitoring (UptimeRobot, Grafana, or cloud alerts)
- Configure backup strategy for PostgreSQL
- Seed database with initial opportunities

### User onboarding (Week 16)
- Send invite codes to 10-20 beta users
- Create onboarding documentation (video walkthrough)
- Set up support channel (email, Discord, or GitHub Discussions)
- Monitor user registration and profile creation

### Feedback collection (Weeks 17-18)
- Review admin dashboard metrics daily
- Collect thumbs up/down feedback on matches
- Interview 5-10 users about their experience
- Document feature requests and pain points
- Prioritize fixes for critical issues

### Iteration (Weeks 17-18)
- Fix critical bugs found by users
- Improve match quality based on feedback
- Enhance explainability based on user questions
- Optimize performance based on real usage patterns

### Production readiness (Week 14-15)
- **Error tracking:** Sentry or similar
- **Monitoring:** health checks, source health dashboard
- **Rate limiting:** per-user API limits
- **Caching:** Redis for match results (deterministic = safe to cache)
- **Deployment:** Docker + docker-compose

---

## Month 4 — Private Beta (Weeks 16-19)

Goal: 10-20 beta users, real feedback.

- **Beta invite system** (email-only, manual approval)
- **User onboarding flow** (guided profile creation)
- **Feedback collection:** thumbs up/down on matches
- **Bug fixes from real usage**
- **Performance optimization:** query tuning, pagination

---

## Month 5 — Public Launch (Weeks 20-23)

Goal: Free public launch.

- **Landing page** (product marketing, features, testimonials)
- **Documentation** (getting started, API docs, FAQ)
- **SEO** (blog posts, academic community outreach)
- **Monitoring + alerting** (error tracking, source health)
- **Donation/support model** (if not freemium)

---

## Month 6 — Growth (Weeks 24-27)

Goal: Feedback-driven expansion.

- **Feedback-driven ranking improvements** (ML layer on top of deterministic base)
- **Expand from PhD-only to postdoc/faculty/staff roles**
- **International expansion:** more languages, more regional sources
- **Partnership integrations** (university career services)
- **Mobile-responsive dashboard**

---

## Release Rules

1. Do not begin the next phase until the previous phase is testable and stable
2. `--self-test` must pass after every migration step
3. LLM is used for extraction, explanation, and drafting — never as the sole ranking mechanism
4. Ranking stays deterministic and independently testable at every dimension
5. No breaking API changes without versioning

## Key Decisions Made

| Decision | Resolution | Date |
|----------|-----------|------|
| LLM provider | LiteLLM + OpenAI default + Ollama fallback | 2026-08-03 |
| Database | SQLite for MVP, SQLAlchemy 2.0 | 2026-08-03 |
| Matching dimensions | 3 for MVP (topic/method/location), 7 total | 2026-08-03 |

## Key Decisions Remaining

| Decision | Blocks | Urgency |
|----------|--------|---------|
| Auth strategy | Month 2 (dashboard) | **High** — resolve before Week 8 |
| Frontend framework | Month 2 (dashboard) | **High** — recommend Next.js + shadcn/ui |
| Hosting target | Month 5 (launch) | Low — can defer to Month 4 |
