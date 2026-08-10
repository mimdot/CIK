# Sprint 04: FastAPI REST API + Dashboard Foundation

**Duration:** Weeks 8-9 (2026-08-04 → 2026-08-17)
**Goal:** Build the FastAPI REST API that exposes all backend functionality, wire it to the existing modules, and lay the foundation for the dashboard UI

---

## What shipped in Sprints 01-03 (for context)

| Item | Status |
|------|--------|
| Migration Steps 1-12 (full monolith decomposition) | DONE |
| Profile engine (LLM + schema + extraction) | DONE + wired |
| Database (7 models + repos + seed) | DONE + wired |
| Matching engine (3 dimensions + explainability) | DONE |
| CLI (`--build-profile`, `--seed-db`, `--show-profile`, `--run` with profile) | DONE |
| Monolith: 7,368 → 515 lines | DONE |
| Tests: 303 passing | DONE |

---

## Track A: FastAPI REST API (Weeks 8-9)

### A1: Project structure + FastAPI app setup
**Effort:** 0.5 days
**Deliverable:** `api/` package with `__init__.py`, `app.py`, `deps.py`

```python
# api/app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Career Intelligence API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

# api/deps.py
def get_db() -> Session:
    """Yield a SQLAlchemy session for dependency injection."""
    engine = init_db(DEFAULT_DB_URL)
    with Session(engine) as session:
        yield session

def get_profile(session: Session) -> Optional[UserProfile]:
    """Return the active profile or None."""
    row = ProfileRepo(session).get_active()
    return UserProfile(**row.to_profile()) if row else None
```

Install: `pip install fastapi uvicorn[standard]`

### A2: Profile endpoints
**Effort:** 1 day
**Deliverable:** `api/routes/profile.py`

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/profile` | GET | — | `UserProfile` (active profile or 404) |
| `/api/profile/build` | POST | `{"raw_text": "CV text..."}` | `UserProfile` (extracted + saved) |
| `/api/profile` | PUT | `UserProfile` fields | `UserProfile` (updated) |

```python
# api/routes/profile.py
from fastapi import APIRouter, Depends, HTTPException
from core.profile_schema import UserProfile

router = APIRouter(prefix="/api/profile", tags=["profile"])

@router.get("/")
def get_profile(profile: Optional[UserProfile] = Depends(get_profile_dep)):
    if profile is None:
        raise HTTPException(404, "No active profile")
    return profile

@router.post("/build")
def build_profile(body: BuildProfileRequest, db: Session = Depends(get_db)):
    llm = LLMRouter()
    profile = extract_profile(body.raw_text, llm)
    if profile is None:
        raise HTTPException(422, "Could not extract profile from text")
    repo = ProfileRepo(db)
    repo.deactivate_all()
    repo.create(profile.model_dump())
    db.commit()
    return profile
```

### A3: Opportunities + Matches endpoints
**Effort:** 1 day
**Deliverable:** `api/routes/opportunities.py`, `api/routes/matches.py`

| Endpoint | Method | Query params | Response |
|----------|--------|-------------|----------|
| `/api/opportunities` | GET | `?country=&source=&type=&page=&limit=` | `List[Opportunity]` |
| `/api/opportunities/{id}` | GET | — | `Opportunity` |
| `/api/matches` | GET | `?min_score=&limit=` | `List[MatchResult]` with explanation |
| `/api/matches/{id}/feedback` | POST | `{"helpful": true, "comment": "..."}` | 200 |

### A4: Supervisors endpoint
**Effort:** 0.5 days
**Deliverable:** `api/routes/supervisors.py`

| Endpoint | Method | Query params | Response |
|----------|--------|-------------|----------|
| `/api/supervisors` | GET | `?country=&field=&limit=` | `List[Supervisor]` |
| `/api/supervisors/{id}` | GET | — | `Supervisor` |

### A5: Bookmarks + Feedback endpoints
**Effort:** 0.5 days
**Deliverable:** `api/routes/bookmarks.py`, `api/routes/feedback.py`

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/bookmarks` | GET | — | `List[Bookmark]` |
| `/api/bookmarks` | POST | `{"opportunity_id": 123}` | `Bookmark` |
| `/api/bookmarks/{id}` | DELETE | — | 200 |
| `/api/feedback` | POST | `{"match_id": 5, "helpful": true}` | 200 |

### A6: Pipeline trigger endpoint
**Effort:** 0.5 days
**Deliverable:** `api/routes/pipeline.py`

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/pipeline/run` | POST | `{"sources": ["eso", "euraxess"], "country": "Germany"}` | `{"status": "started", "run_id": "..."}` |
| `/api/pipeline/status` | GET | `?run_id=...` | `{"status": "completed", "records": 150}` |

This triggers the existing `run()` function in a background thread (not Celery yet — MVP simplicity).

### A7: API tests
**Effort:** 1 day
**Deliverable:** `tests/test_api.py`

- Test every endpoint with FastAPI's `TestClient`
- Mock the LLM for `/api/profile/build`
- Use in-memory SQLite for all DB tests
- Test error cases (404, 422, 500)
- Test pagination
- Test authentication (when A8 is done)

---

## Track B: Dashboard Foundation (Week 9)

### B1: Next.js project setup
**Effort:** 0.5 days
**Deliverable:** `dashboard/` directory with Next.js + shadcn/ui

```bash
npx create-next-app@latest dashboard --typescript --tailwind --app
cd dashboard && npx shadcn@latest init
```

Install shadcn components: `button`, `card`, `input`, `select`, `table`, `dialog`, `badge`, `toast`

### B2: API client + types
**Effort:** 0.5 days
**Deliverable:** `dashboard/lib/api.ts`, `dashboard/types/index.ts`

```typescript
// dashboard/types/index.ts
export interface UserProfile {
  domain: string;
  subfield?: string;
  methods: string[];
  tools: string[];
  skills: string[];
  experience_level: string;
  countries_preferred: string[];
  confidence: number;
}

export interface Opportunity {
  id: number;
  title: string;
  institution?: string;
  country?: string;
  url?: string;
  match_score?: number;
  match_explanation?: string;
  deadline?: string;
  position_type?: string;
  source?: string;
}

// dashboard/lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchProfile(): Promise<UserProfile | null> { ... }
export async function buildProfile(cvText: string): Promise<UserProfile> { ... }
export async function fetchMatches(minScore?: number): Promise<Opportunity[]> { ... }
export async function fetchOpportunities(filters: OpportunityFilters): Promise<Opportunity[]> { ... }
```

### B3: Dashboard layout + navigation
**Effort:** 0.5 days
**Deliverable:** `dashboard/app/layout.tsx`, `dashboard/components/Nav.tsx`

Pages:
- `/` — Dashboard (match cards)
- `/profile` — Profile builder
- `/opportunities` — All opportunities with filters
- `/supervisors` — Supervisor candidates
- `/bookmarks` — Saved positions

### B4: Profile builder page
**Effort:** 0.5 days
**Deliverable:** `dashboard/app/profile/page.tsx`

- Text area for CV/bio paste
- "Build Profile" button → calls `/api/profile/build`
- Displays extracted profile with confidence score
- Edit capability for manual overrides

### B5: Match cards page
**Effort:** 1 day
**Deliverable:** `dashboard/app/page.tsx`, `dashboard/components/MatchCard.tsx`

- Cards sorted by match_score
- Each card shows: title, institution, country, match score (0-1), explainability text
- Filters: country, source, position type
- Search bar
- Click to expand full details + link to original posting

### B6: Dashboard tests
**Effort:** 0.5 days
**Deliverable:** `dashboard/__tests__/` with Jest + React Testing Library

- Test profile builder renders and submits
- Test match cards render with scores
- Test filters work
- Test error states (API down, empty results)

---

## Track C: Auth Foundation (Week 9, parallel)

### C1: User model + auth endpoints
**Effort:** 1 day
**Deliverable:** `api/routes/auth.py`, update `db/models.py`

Add `User` model to `db/models.py`:
```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

Endpoints:
| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/auth/register` | POST | `{"email": "...", "password": "..."}` | `{"user_id": 1}` |
| `/api/auth/login` | POST | `{"email": "...", "password": "..."}` | `{"access_token": "..."}` |
| `/api/auth/me` | GET | — | `{"user_id": 1, "email": "..."}` |

Use bcrypt for password hashing, JWT for tokens (via `python-jose`).

### C2: Auth middleware + profile scoping
**Effort:** 0.5 days

- All `/api/profile`, `/api/matches`, `/api/bookmarks` endpoints require auth
- Profile is scoped to the authenticated user (`profile.user_id`)
- Matches are scoped to the user's profile
- Bookmarks are scoped to the user

### C3: Auth tests
**Effort:** 0.5 days

- Test registration, login, token validation
- Test unauthorized access returns 401
- Test profile scoping (user A can't see user B's profile)

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (FastAPI setup) | `uvicorn api.app:app` starts, `/docs` shows OpenAPI |
| A2 (Profile endpoints) | GET/POST/PUT work, tested |
| A3 (Opportunities + Matches) | Endpoints return data, pagination works |
| A4 (Supervisors) | Endpoint returns ranked supervisors |
| A5 (Bookmarks + Feedback) | CRUD works |
| A6 (Pipeline trigger) | POST triggers run in background |
| A7 (API tests) | 50+ API tests pass |
| B1 (Next.js setup) | `npm run dev` starts dashboard |
| B2 (API client) | Types match backend, fetch functions work |
| B3 (Layout) | Navigation works, pages load |
| B4 (Profile page) | Can paste CV and see extracted profile |
| B5 (Match cards) | Cards render with scores and explanations |
| B6 (Dashboard tests) | Jest tests pass |
| C1 (Auth model) | User registration + login work |
| C2 (Auth middleware) | Protected endpoints require token |
| C3 (Auth tests) | Auth tests pass |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| FastAPI + SQLAlchemy async complexity | Start synchronous, add async later if needed |
| Next.js setup overhead | Use `create-next-app` defaults, don't over-engineer |
| Auth security | Use bcrypt + JWT best practices, don't roll your own crypto |
| CORS issues | Configure origins properly, test cross-origin early |
| API ↔ frontend type drift | Generate types from OpenAPI schema (`openapi-typescript`) |

---

## Sprint 04 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_04.md
2. /home/mohammad-reza/career_intelligence_kit/db/models.py
3. /home/mohammad-reza/career_intelligence_kit/cli/commands.py
4. /home/mohammad-reza/career_intelligence_kit/matching/scorer.py

Then execute Sprint 04 from SPRINT_04.md, in this order:

TRACK A — FASTAPI REST API:

A1. Create api/ package: api/__init__.py, api/app.py, api/deps.py. Set up FastAPI app with CORS, health check endpoint. Install fastapi + uvicorn. Verify: `uvicorn api.app:app` starts, /docs shows OpenAPI.

A2. Create api/routes/profile.py with GET /api/profile (return active profile or 404), POST /api/profile/build (accept {"raw_text": "..."}, extract via LLM, save to DB, return profile), PUT /api/profile (update active profile). Test with TestClient.

A3. Create api/routes/opportunities.py with GET /api/opportunities (list with filters: country, source, type, pagination), GET /api/opportunities/{id}. Create api/routes/matches.py with GET /api/matches (list matches sorted by score, with explainability), POST /api/matches/{id}/feedback. Test.

A4. Create api/routes/supervisors.py with GET /api/supervisors (list with country/field filters). Test.

A5. Create api/routes/bookmarks.py with GET /api/bookmarks, POST /api/bookmarks, DELETE /api/bookmarks/{id}. Test.

A6. Create api/routes/pipeline.py with POST /api/pipeline/run (trigger run() in background thread), GET /api/pipeline/status. Test.

A7. Create tests/test_api.py with TestClient tests for all endpoints. Use in-memory SQLite. Mock LLM. Target: 50+ tests.

TRACK B — DASHBOARD FOUNDATION:

B1. Create dashboard/ with Next.js + shadcn/ui: `npx create-next-app@latest dashboard --typescript --tailwind --app`. Install shadcn components. Verify: `npm run dev` starts.

B2. Create dashboard/types/index.ts (UserProfile, Opportunity, Match types matching backend). Create dashboard/lib/api.ts (fetch functions for all endpoints).

B3. Create dashboard/app/layout.tsx with navigation (Dashboard, Profile, Opportunities, Supervisors, Bookmarks). Create dashboard/components/Nav.tsx.

B4. Create dashboard/app/profile/page.tsx — text area for CV, "Build Profile" button, displays extracted profile.

B5. Create dashboard/app/page.tsx with MatchCard component — cards sorted by match_score, show title/institution/country/score/explanation. Add filters (country, source, type).

B6. Create dashboard/__tests__/ with Jest tests for profile page and match cards.

TRACK C — AUTH FOUNDATION:

C1. Add User model to db/models.py (email, hashed_password, created_at). Create api/routes/auth.py with POST /api/auth/register (bcrypt hash), POST /api/auth/login (JWT token), GET /api/auth/me. Install python-jose + passlib[bcrypt].

C2. Add auth dependency to api/deps.py — require JWT token for /api/profile, /api/matches, /api/bookmarks. Scope profile/matches/bookmarks to authenticated user.

C3. Add auth tests to tests/test_api.py — registration, login, token validation, unauthorized access returns 401.

RULES:
- Backend API must be RESTful and match the OpenAPI spec.
- Dashboard must be responsive (mobile-friendly).
- Auth must use bcrypt + JWT (never store plaintext passwords).
- All endpoints must have tests.
- Run `python -m pytest tests/ -q` after every backend change.
- Run `npm test` after every frontend change.
- The existing CLI (`phd_aggregator.py`) must keep working unchanged.
```
