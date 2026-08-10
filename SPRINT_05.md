# Sprint 05: Complete Dashboard + Production Hardening

**Duration:** Weeks 12-14 (2026-08-04 → 2026-08-25)
**Goal:** Finish all dashboard pages, add Docker deployment, prepare for private beta

---

## What shipped in Sprints 01-04 (for context)

| Item | Status |
|------|--------|
| Migration Steps 1-12 (full decomposition) | DONE |
| Profile engine + DB + matching engine | DONE |
| CLI (`--build-profile`, `--run`, `--seed-db`) | DONE |
| FastAPI API (15 endpoints, auth, rate limiting) | DONE |
| Dashboard foundation (onboarding + match cards) | DONE |
| Auth (bcrypt + JWT + httpOnly cookie) | DONE |
| Tests: 404 passing | DONE |

---

## Track A: Dashboard Completion (Weeks 12-13)

### A1: Profile view/edit page
**Effort:** 1 day
**Deliverable:** `dashboard/app/profile/page.tsx`

- Display current profile (GET /api/profile)
- Edit form for all fields (PUT /api/profile)
- "Re-build from CV" button (POST /api/profile/build)
- Confidence score display
- Toast notifications for save success/error

### A2: Supervisor view page
**Effort:** 1 day
**Deliverable:** `dashboard/app/supervisors/page.tsx`

- List supervisors from /api/supervisors
- Filters: country, field/topic, sort by score
- Click to expand: institution, topics, papers, ORCID link
- Search bar

### A3: Bookmarks page
**Effort:** 1 day
**Deliverable:** `dashboard/app/bookmarks/page.tsx`

- List bookmarks with opportunity details
- Delete button with confirmation dialog
- Sort by date added
- Link to original opportunity

### A4: Settings page
**Effort:** 0.5 days
**Deliverable:** `dashboard/app/settings/page.tsx`

- Field profile selection (dropdown of available profiles)
- Email digest preferences (frequency, quiet days)
- Account info display

### A5: Dashboard polish
**Effort:** 0.5 days

- Loading states (skeletons) for all pages
- Error boundaries
- Toast notification system (shadcn/ui)
- Mobile responsive (test at 375px width)
- Empty states ("No matches yet — build your profile")

---

## Track B: Production Hardening (Week 14)

### B1: Docker + docker-compose
**Effort:** 1 day
**Deliverable:** `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`

```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      - CIK_SECRET_KEY=${CIK_SECRET_KEY}
      - DATABASE_URL=sqlite:///data/phd_data.db
    volumes: ["./data:/data"]
  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_URL=http://api:8000
```

### B2: Environment config
**Effort:** 0.5 days
**Deliverable:** `.env.example`, `docker-compose.env`

```env
CIK_SECRET_KEY=generate-with-openssl-rand-hex-32
DATABASE_URL=sqlite:///data/phd_data.db
LLM_DEFAULT_MODEL=openai/gpt-4o-mini
OPENALEX_MAILTO=your@email.com
```

### B3: Production CORS + security headers
**Effort:** 0.5 days
**Deliverable:** Update `api/app.py`

- CORS: only allow production domain origins
- Security headers: X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security
- Rate limit headers: X-RateLimit-Limit, X-RateLimit-Remaining

### B4: Health check + readiness probe
**Effort:** 0.5 days
**Deliverable:** Update `api/app.py`

- `/health` — liveness (already exists)
- `/ready` — readiness (DB accessible, LLM configured)

---

## Track C: Explainability + Polish (Week 14, parallel)

### C1: Match explanation improvements
**Effort:** 0.5 days
**Deliverable:** Update `matching/scorer.py`

- Add comparative text: "This position is more relevant than X% of opportunities"
- Add missing skills suggestions: "Consider learning: X, Y"
- Store comparison percentile in MatchResult

### C2: Dashboard API docs
**Effort:** 0.5 days
**Deliverable:** `dashboard/docs/API.md`

- Document all 15 endpoints
- Request/response examples
- Authentication flow diagram
- Error codes

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (Profile page) | Can view and edit profile in dashboard |
| A2 (Supervisors page) | Can search and filter supervisors |
| A3 (Bookmarks page) | Can list, delete bookmarks |
| A4 (Settings page) | Can select field profile, view preferences |
| A5 (Polish) | All pages responsive, loading states, error handling |
| B1 (Docker) | `docker-compose up` starts both services |
| B2 (Env config) | `.env.example` documents all required vars |
| B3 (CORS) | Production CORS blocks localhost |
| B4 (Readiness) | `/ready` returns 200 when DB + LLM available |
| C1 (Explainability) | Match cards show comparative + suggestions |
| C2 (API docs) | All endpoints documented |

---

## Sprint 05 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_05.md
2. /home/mohammad-reza/career_intelligence_kit/dashboard/app/page.tsx (existing dashboard)
3. /home/mohammad-reza/career_intelligence_kit/api/routes/matches.py

Then execute Sprint 05 from SPRINT_05.md, in this order:

TRACK A — DASHBOARD COMPLETION:

A1. Create dashboard/app/profile/page.tsx — Profile view/edit page. Display current profile from GET /api/profile. Edit form for all fields using PUT /api/profile. "Re-build from CV" button. Confidence score display. Toast on save.

A2. Create dashboard/app/supervisors/page.tsx — Supervisor view page. List from /api/supervisors. Filters: country, field, sort by score. Expandable cards with institution, topics, papers, ORCID link. Search bar.

A3. Create dashboard/app/bookmarks/page.tsx — Bookmarks page. List with opportunity details. Delete with confirmation dialog. Sort by date added. Link to original.

A4. Create dashboard/app/settings/page.tsx — Settings page. Field profile dropdown. Email preferences. Account info.

A5. Polish: Add loading skeletons (shadcn/ui Skeleton component) to all pages. Add error boundaries. Add toast notifications. Test at 375px mobile width. Add empty states.

TRACK B — PRODUCTION HARDENING:

B1. Create Dockerfile at project root:
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY phd_aggregator/ ./phd_aggregator/
   WORKDIR /app/phd_aggregator
   CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
   Create docker-compose.yml with api + dashboard services.
   Create docker-compose.prod.yml with production overrides.

B2. Create .env.example at project root documenting all env vars: CIK_SECRET_KEY, DATABASE_URL, LLM_DEFAULT_MODEL, LLM_FALLBACK_MODEL, OPENALEX_MAILTO, ADS_API_TOKEN.

B3. Update api/app.py — Add production CORS (configurable origins via CORS_ORIGINS env var). Add security headers middleware (X-Content-Type-Options: nosniff, X-Frame-Options: DENY, X-XSS-Protection: 1; mode=block).

B4. Add /ready endpoint to api/app.py — Check DB is accessible, return 200 if OK, 503 if not.

TRACK C — EXPLAINABILITY:

C1. Update matching/scorer.py — In explain_match(), add a comparative line: "This position is more relevant than X% of opportunities." (requires knowing the full score distribution, which the API matches endpoint now has via cache). Add "Consider learning: X, Y" for missing top methods.

C2. Create dashboard/docs/API.md — Document all 15 endpoints with request/response examples, auth flow, error codes.

RULES:
- Dashboard must be responsive (test at mobile + desktop widths).
- All API changes must pass python -m pytest tests/test_api.py -q.
- Docker must work with docker-compose up (no manual steps).
- No breaking changes to existing API endpoints.
```
