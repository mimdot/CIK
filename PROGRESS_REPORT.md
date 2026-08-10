# Progress Report — Sprint 09: AI Features + AI Ops

**Date:** 2026-08-09
**Scope:** Sprint 09 implementation (Track A: Product AI, Track B: AI Ops, Track C: AI Safety) — completed.
**Plan source:** `SPRINT_09.md`

---

## Status

| Item | Status | Key files |
|------|--------|-----------|
| A1: Assistant drafting | DONE | `phd_aggregator/core/assistant.py` |
| A2: Assistant endpoints + quota | DONE | `phd_aggregator/api/routes/assistant.py`, `dashboard/components/CoverLetterModal.tsx` |
| A3: Digest v2 (LLM reason rewrite + fallback) | DONE | `phd_aggregator/core/digest.py` |
| A4: Explainability v2 (next_actions) | DONE | `phd_aggregator/matching/scorer.py`, `phd_aggregator/api/routes/matches.py`, `dashboard/components/MatchCard.tsx` |
| A5: Product-AI tests | DONE | `tests/test_assistant_routes.py` |
| B1: Source-health monitor + drift alerts | DONE | `phd_aggregator/core/source_monitor.py`, `phd_aggregator/core/notify.py`, `phd_aggregator/pipeline/run.py` |
| B2: Feedback intelligence | DONE | `phd_aggregator/core/feedback_intel.py` |
| B3: Self-healing jobs + heartbeat | DONE | `phd_aggregator/core/tasks.py` |
| B4: API anomaly detection | DONE | `phd_aggregator/core/anomaly.py` |
| C1: LLM accounting + cap + toggles | DONE | `phd_aggregator/core/llm.py`, `phd_aggregator/db/models.py` |
| C2: Audit hookups + metrics extension | DONE | `phd_aggregator/api/routes/admin.py` |
| Admin dashboard ops-intel UI | DONE | `dashboard/app/admin/page.tsx` |
| Frontend API client + types | DONE | `dashboard/lib/api.ts`, `dashboard/types/index.ts` |

## Regression

- Backend: **643 tests pass** (`python3 -m pytest tests/ -q` in `phd_aggregator/`).
- Frontend: **58 tests pass** (`npx jest --silent` in `dashboard/`).
- TypeScript: `npx tsc --noEmit` exits 0.
- Build: `next build` compiles green.

## Known caveats

- `npm run lint` is blocked by a **pre-existing** ESLint 9.30.0 flat-config error:
  `ESLint couldn't find a valid languageOptions.ecmaVersion`. It reproduces on
  untouched files (e.g. `dashboard/components/ui/button.tsx`), so it is not caused
  by this work. Until fixed, use `tsc --noEmit` + `next build` + jest as the gate.
- The repo has no `.git` directory; version control has not been configured.

## Key implementation details

- **Feature toggles / quotas**
  - `ASSISTANT_ENABLED` toggle; `DIGEST_LLM_ENABLED` toggle.
  - `ASSISTANT_DAILY_LIMIT` env (default 50) — per-user soft quota via
    `core/ratelimit.RedisRateLimiter(50, 24*3600, prefix="assistant")`,
    key `user:{user.id}`; exceeded → 429.
  - `LLM_MONTHLY_CAP_USD` (default off) enforced in `core/llm.py` via a model-prices map.
- **Source-health (B1):** `DRIFT_Z = 2.5`, `MAX_ERRORS = 3`, alert debounce 1/source/hour.
  Channel: Sentry `capture_message` → `OPS_WEBHOOK_URL` → log; never raises.
- **Anomaly (B4):** `ERROR_Z = 2.5`, `MIN_ERRORS = 5`, `MIN_LATENCY_MS = 800`,
  `SLOT_S = 60`, `WINDOW_SLOTS = 60`, debounce 1/metric/hour.
  `MetricsMiddleware` in `api/app.py` feeds `anomaly.submit(...)`; in-memory fallback when Redis absent.
- **Tasks (B3):** `MAX_PIPELINE_RETRIES = max(0, int(os.environ.get("CIK_JOB_RETRIES", "2")))`;
  `CIK_JOB_RETRY_DELAY` for backoff (default 2 s). In-memory job records store
  `country`/`sources`/`created_at`/`attempts`. Intermediate retries do NOT release
  `_fallback_slots` (only `is_final` attempts do).
- **Admin endpoints added** (all in `phd_aggregator/api/routes/admin.py`):
  `GET /api/admin/source-health`, `POST /api/admin/source-health/check-drift`,
  `GET /api/admin/feedback-intel`, `GET /api/admin/tasks/dead-letters`,
  `POST /api/admin/tasks/{job_id}/retry`, `GET /api/admin/tasks/worker-heartbeat`,
  `GET /api/admin/anomalies`, `POST /api/admin/anomalies/detect`;
  `GET /api/admin/metrics` extended with `llm` (calls/spend via `LlmUsage` +
  `core.llm.estimate_cost_usd`) and `source_health` (drifted/erroring counts).
- **Assistant endpoints** (`phd_aggregator/api/routes/assistant.py`):
  `POST /api/assistant/cover-letter`, `POST /api/assistant/application-email`,
  `POST /api/assistant/cv-improvements`, `GET /api/assistant/usage`.
- **Regression note (from earlier debugging):** `/api/opportunities` is GET-only —
  tests insert rows via `db_session`, never POST. Profile-build returns 201.
  FastAPI evaluates `Depends(...)` defaults at import time, so admin endpoints must be
  defined after `get_admin_user` (a previous NameError). The app's catch-all
  `@app.exception_handler(Exception)` can shadow HTTPException-to-404; routes return
  JSON status instead of raising for "no object" cases.
- **C2 audit:** `log_audit` hooks on `admin.source_drift_check`, `admin.job_retry`,
  `admin.anomaly_detect`.
- Repository layout: backend at `phd_aggregator/`, frontend at `dashboard/`.