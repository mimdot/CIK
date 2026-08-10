# Sprint 09: AI Features + AI Ops

**Duration:** Weeks 5-7 (target: 2026-09-15 → 2026-10-05)
**Goal:** Two complementary AI tracks. **(A) Product AI** — user-facing LLM
assistance (cover-letter drafting, CV suggestions, digest personalization,
deeper explainability) while keeping the ranking deterministic. **(B) AI Ops**
— the "handle the project fully" layer: live source-health monitoring with
drift alerts, feedback intelligence, self-healing jobs, and API anomaly
detection. The LLM **supports** the system; it never defines ranking.

---

## What shipped in Sprints 01-08 (for context)

| Item | Status |
|------|--------|
| Full backend + dashboard + docker + email service + public API keys | DONE |
| Security: Redis rate limit, CSRF, audit log, password reset | DONE |
| Tests: 452 + Sprints 07-08 additions passing | DONE |

---

## Track A: Product AI (user-facing)

### A1: Cover-letter / application-email drafting — `core/assistant.py`
**Effort:** 2 days
**Deliverable:** `core/assistant.py` + `api/routes/assistant.py` + tests

```python
# core/assistant.py — LLM-assisted drafting. Reuses core.llm.LLMRouter.
from core.llm import LLMRouter
from core.profile_schema import UserProfile

def draft_cover_letter(profile: UserProfile, opportunity: dict,
                       tone: str = "professional", length: str = "medium") -> dict:
    """Generate a cover letter from profile + opportunity + match explanation.

    Returns {"text": ..., "model": ..., "token_count": ...}. The LLM is a
    DRAFTING tool only — the user edits before sending."""
```

- Prompt template: profile fields, the opportunity's key facts (title,
  institution, deadline, funding), and the existing deterministic
  `match_explanation`. Instruct the LLM to ground every sentence in the given
  facts (no invented skills).
- **Safety rails**:
  - Token cap per call + `temperature=0.3`.
  - The drafted text is **never auto-submitted** — the dashboard shows an
    editable draft in the application modal.
  - Rate-limited per user (reuse the Redis limiter from Sprint 07).
- Also `draft_application_email()` (shorter, for the "email the PI" flow) and
  `suggest_cv_improvements(profile)` (lists skill/tool gaps from recent
  high-fit-but-failed matches).
- Tests: inject a fake LLM backend (same pattern as `tests/test_profile_engine.py`)
  and assert the prompt contains the opportunity facts; no network in tests.

### A2: Assistant endpoints — `api/routes/assistant.py`
**Effort:** 0.5 days
**Deliverable:** `api/routes/assistant.py` + tests

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/assistant/cover-letter` | POST | user | `{opportunity_id, tone?, length?}` → draft |
| `/api/assistant/application-email` | POST | user | `{opportunity_id}` → short email draft |
| `/api/assistant/cv-improvements` | POST | user | → `{improvements: [...]}` from recent matches |
| `/api/assistant/usage` | GET | user | per-user LLM call count (for a soft cap) |

- **Soft per-user LLM quota** (e.g. 50 drafts/day) — enforced with the same
  Redis limiter; exceeded → 429 with a friendly message.
- Wire the cover-letter draft into the **dashboard application modal**
  (`dashboard/app/opportunities/page.tsx` + a new `CoverLetterModal` component)
  with an editable textarea, "copy" and "download" actions.

### A3: Digest personalization — `core/digest.py` v2
**Effort:** 1 day
**Deliverable:** `core/digest.py` + tests

- Keep the **deterministic selection** (score > 0.85, ≤5, deadline sort).
- Add LLM **reason rewriting**: for each of the top items, ask the LLM to turn
  the structured `match_explanation` into one plain-language sentence
  ("Why this fits you"). If the LLM fails or is rate-limited, fall back to the
  deterministic explanation — **the digest must never fail because the LLM
  did**.
- Batch in a single completion call per digest (list → list), with a strict
  JSON schema and validation (`extract_json_block` in `core/llm.py:103`).
- Tests: fake LLM returns rewritten reasons; fake LLM failing → fallback text.

### A4: Explainability v2 — "What to do next"
**Effort:** 1 day
**Deliverable:** extend `matching/scorer.py` + `api/routes/matches.py`

- Add a **deterministic** `next_actions` generator to each match:
  1. Read the posting's deadline → "Apply by <date>".
  2. Read funding_status → "Funding: fully funded / check funding".
  3. Missing methods (`missing_methods`) → "Strengthen: <top 3>".
  4. Location mismatch → "Requires relocation to <country>".
- Optional LLM layer: a single call that turns the deterministic
  `explanation` + `next_actions` into a tighter paragraph — again with a
  **fallback to the deterministic text**. Never part of the score.
- Dashboard `MatchCard.tsx` renders a "Next steps" list per card.

### A5: Product-AI tests
**Effort:** 0.5 days

- Drafting: prompt contains opportunity facts; fake backend returns editable text.
- Digest v2: LLM success path + fallback path both covered.
- Explainability: `next_actions` is pure/deterministic and unit-tested.
- Dashboard: CoverLetterModal renders, submits, and shows the draft.

---

## Track B: AI Ops (operations automation)

### B1: Live source-health monitor — `core/source_monitor.py`
**Effort:** 1.5 days
**Deliverable:** `core/source_monitor.py` + `api/routes/admin.py` + tests

Turns the one-off `SOURCE_HEALTH.md` audit into a **living system**:

```python
# core/source_monitor.py
def record_run(source: str, raw_records: int, kept: int, duration_s: float) -> None:
    """Append a per-source measurement to Redis (rolling window, 30 runs)."""

def source_health(session) -> list[dict]:
    """For each source: last run, mean/std of raw_records over the window,
    z-score of the latest run, drift flag if |z| > 2.5."""

def check_drift() -> list[dict]:
    """Flag sources whose latest run is an outlier vs baseline → alert payload."""
```

- **Data source**: instrument `pipeline/run.py` to call `record_run` for each
  source after every pipeline job (both CLI and rq worker paths).
- **Drift alert**: when `|z-score| > 2.5` or a source errors 3× in a row, emit
  an alert to Sentry (`sentry_sdk.capture_message`) and a webhook
  (`OPS_WEBHOOK_URL`, e.g. Slack/Telegram/Discord). Degrades to a log line if
  neither is configured.
- Admin endpoint `GET /api/admin/source-health` → new admin dashboard tab
  showing the table with drift badges.
- Tests: with a fake baseline, verify z-score computation and the alert
  payload; no network.

### B2: Feedback intelligence — `core/feedback_intel.py`
**Effort:** 1 day
**Deliverable:** `core/feedback_intel.py` + `api/routes/admin.py` + tests

- Aggregate `MatchFeedback` (thumbs down + comments) weekly:
  - **Cluster**: LLM groups free-text comments into themes (e.g. "matches
    irrelevant", "deadline confusing", "too many astronomy posts").
  - **Prioritize**: for each theme, output `{theme, count, example_comments,
    suggested_action}` — an auto-prioritized backlog for the maintainer.
- Guardrails: only comments from real users (≥1 profile, not test accounts);
  cap LLM input; a deterministic fallback counts keyword buckets when the LLM
  is unavailable.
- Admin endpoint `GET /api/admin/feedback-intel` + dashboard tab; results
  cached for 24 h (`core.cache`).
- Tests: fake LLM returns a theme JSON; fallback path when LLM fails.

### B3: Self-healing jobs — `core/tasks.py` addition
**Effort:** 1 day
**Deliverable:** `core/tasks.py` + tests

- **Retry with backoff**: rq jobs already accept `retries`; set
  `retries=3, retry=ExponentialBackoff` for pipeline + digest jobs.
- **Dead-letter review**: a nightly job scans `FailedJobRegistry` and re-enqueues
  jobs whose errors are transient (HTTP 5xx, proxy drop), capped to prevent
  a poisoned loop (max 2 re-enqueues per job id; jobs flagged with a tag).
- **Worker heartbeat + auto-restart**: the worker writes a heartbeat key in
  Redis every 30 s; the health monitor flags a worker as stale after 3 missed
  beats and the compose `restart: unless-stopped` policy restarts it.
- **Cache self-heal**: on pipeline completion, `cache.invalidate_*` already
  runs (`core/tasks.py:53`); extend to also warm the supervisor list.
- Tests: exponential-backoff config present; re-enqueue skips jobs already
  retried twice; heartbeat writes/staleness detection.

### B4: API anomaly detection — `core/anomaly.py`
**Effort:** 1 day
**Deliverable:** `core/anomaly.py` + `api/routes/admin.py` + tests

- The in-process metrics (`api/metrics.py`) reset on restart and have no
  history. Add a **Redis-backed rolling store** (windowed counters per minute)
  while keeping `metrics` as the low-level recorder:
  - Error-rate and p95-latency tracked per minute for the last 60 minutes.
  - **Detector** (daily job + on-request): flag when the latest 10-minute error
    rate is > 3× the trailing 60-min baseline, or p95 exceeds a configured
    ceiling.
- Alert through the same `notify_ops(message)` channel as B1.
- Admin endpoint `GET /api/admin/anomalies` + dashboard tab (last 24 h, flags).
- Tests: inject synthetic metric series; assert the flag logic; no network.

---

## Track C: AI Safety + Guardrails (horizontal)

### C1: LLM call accounting + cost guard — `core/llm.py` addition
**Effort:** 0.5 days
**Deliverable:** `core/llm.py` + `db/models.py` + tests

- Record every LLM call in a new `llm_usage` table:
  `{user_id?, feature, model, prompt_tokens, completion_tokens, latency_ms, created_at}`.
- **Global monthly cap** env var `LLM_MONTHLY_CAP_USD` (default off): before
  each call, estimate cost (a small model-prices map) and refuse when over the
  cap — the platform must not surprise the owner with an LLM bill at launch.
- Feature-level toggles env (`ASSISTANT_ENABLED=1`, `DIGEST_LLM_ENABLED=1`)
  so AI features can be cut instantly without a deploy.
- Tests: usage row written; cap enforced with a fake cost map.

### C2: Audit + observability hookups
**Effort:** 0.5 days

- `log_audit` calls around assistant drafts, key revocation (from Sprint 08),
  source-health alerts, and re-enqueued jobs.
- Extend `/api/admin/metrics` to include `llm_usage` totals and
  `source_health` counts so the admin dashboard stays a single pane of glass.

---

## Definition of Done

| Item | Done when |
|------|-----------|
| A1 (Assistant) | Cover letter / app email / CV suggestions draft via LLM; editable; token-capped |
| A2 (Endpoints) | `/api/assistant/*` work with per-user soft quota; dashboard modal wired |
| A3 (Digest v2) | Personalization with deterministic fallback; never fails on LLM outage |
| A4 (Explainability v2) | Deterministic `next_actions` per match; dashboard "Next steps" |
| A5 (Product-AI tests) | All A-track tests pass (fake LLM backend) |
| B1 (Source monitor) | Runs recorded; drift flagged; alert channel works (Sentry/webhook/log) |
| B2 (Feedback intel) | Themes + prioritized backlog; deterministic fallback |
| B3 (Self-healing) | Backoff retries, dead-letter review, heartbeat + restart |
| B4 (Anomaly) | Rolling metrics + detector + admin view |
| C1 (LLM guard) | Usage recorded; monthly cap + feature toggles enforced |
| C2 (Hookup) | Admin dashboard shows LLM usage + source health |
| **Regression** | All existing tests still pass; ranking stays deterministic |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| LLM introduces invented skills into drafts | Fact-grounded prompt + "editable draft, never auto-submit" rule |
| LLM outage breaks the digest | Deterministic fallback for every LLM touchpoint |
| LLM bill runaway at launch | Usage accounting + monthly USD cap + feature toggles |
| Drift alerts spam | z-score threshold, 3-error rule, alert debounce (max 1/hr/source) |
| Feedback themes skewed by few users | Real-user filter, counts shown, LLM is advisory |
| Self-healing re-enqueues poison jobs | Max-2 retries per job, failed jobs tagged and reviewed |
| Metrics are process-local | Rolling store in Redis with in-memory fallback |
| Ranking no longer deterministic | LLM never touches scores — only text generation; `score_match` untouched |

---

## Sprint 09 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_09.md
2. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/core/llm.py
3. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/core/digest.py
4. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/matching/scorer.py
5. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/api/metrics.py
6. /home/mohammad-reza/career_intelligence_kit/phd_aggregator/core/tasks.py

Then execute Sprint 09 from SPRINT_09.md, in this order:

TRACK A — PRODUCT AI:

A1. Create phd_aggregator/core/assistant.py — draft_cover_letter(profile, opportunity, tone, length), draft_application_email(profile, opportunity), suggest_cv_improvements(profile). Uses LLMRouter. Fact-grounded prompts, temperature 0.3, token-capped. Create tests/test_assistant.py (fake LLM backend).
A2. Create phd_aggregator/api/routes/assistant.py — POST /api/assistant/cover-letter, /application-email, /cv-improvements, GET /api/assistant/usage. Per-user soft quota via Redis limiter (default 50/day). Register in api/app.py. Create the CoverLetterModal component in the dashboard and wire it into the opportunities page. Tests.
A3. Update core/digest.py to v2 — LLM rewrites the top items' reasons into one plain sentence each (batched call, JSON schema, validated via extract_json_block). On any LLM failure, fall back to the deterministic explanation. Never fail the digest because the LLM failed. Tests for both paths.
A4. Add deterministic next_actions(profile, opportunity) to matching/scorer.py (deadline → apply-by, funding, missing-methods, relocation). Include next_actions in /api/matches response. Render "Next steps" in dashboard/components/MatchCard.tsx. Tests.
A5. Product-AI tests all pass.

TRACK B — AI OPS:

B1. Create phd_aggregator/core/source_monitor.py — record_run(source, raw_records, kept, duration_s), source_health(session), check_drift(). Instrument pipeline/run.py to call record_run per source. Alert via sentry_sdk.capture_message + OPS_WEBHOOK_URL (fallback: log). Add GET /api/admin/source-health + dashboard tab. Tests with a fake baseline.
B2. Create phd_aggregator/core/feedback_intel.py — cluster comments into themes via LLM, output {theme, count, examples, suggested_action}; deterministic keyword fallback. Add GET /api/admin/feedback-intel + dashboard tab, cached 24h. Tests.
B3. Extend core/tasks.py — retries=3 with ExponentialBackoff for pipeline+digest jobs; nightly dead-letter review re-enqueues transient failures (max 2 per job id); worker heartbeat key every 30s + stale detection (3 missed). Tests.
B4. Create phd_aggregator/core/anomaly.py — Redis rolling per-minute counters (60 min) for error rate + p95; detector flags when 10-min error rate > 3x 60-min baseline or p95 over ceiling; alert via same channel as B1. Add GET /api/admin/anomalies + dashboard tab. Tests.

TRACK C — AI SAFETY:

C1. Add llm_usage table (user_id, feature, model, prompt_tokens, completion_tokens, latency_ms, created_at) and record every LLM call. Enforce LLM_MONTHLY_CAP_USD (default off) via a small model-prices map. Add feature toggles ASSISTANT_ENABLED / DIGEST_LLM_ENABLED. Tests.
C2. Add log_audit calls for assistant drafts, source-health alerts, re-enqueued jobs. Extend /api/admin/metrics with llm_usage totals + source_health counts.

RULES:
- score_match and the ranking MUST stay deterministic — LLM only generates text, never scores.
- Every LLM touchpoint has a deterministic fallback.
- All tests use a fake LLM backend (no network, no real API keys).
- python -m pytest tests/ -q stays green after every change.
- Run npm test after dashboard changes.
```
