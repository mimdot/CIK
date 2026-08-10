# GAP_ANALYSIS.md — Current Implementation vs. PRD & Architecture v1

## Purpose & method

Compares the **working prototype** (`phd_aggregator/` — 13 live sources, field
profiles, supervisor finder, emails) against the **PRD** (`docs/02_PRD_v1.md`),
**Architecture v1** (`docs/03_Architecture_v1.md`), and the v1 specs
(`specs/`). Sources of truth: full read of the 7,368-line monolith, all docs,
prompts, specs, config, and profiles. Findings are labeled, and every missing
component gets a complexity/risk/dependency/milestone estimate.

**Legend**

| Label | Meaning |
|---|---|
| **Existing** | Works today, no gap for v1 |
| **Partial** | A usable slice exists; v1 needs the rest |
| **Missing** | Not present; must be built for v1 |
| **Future** | Explicitly out of v1 scope (roadmap Month 3+) |

---

## Executive summary

- The prototype already covers the **crawler half of the Knowledge Engine**,
  **deterministic topic scoring** (1 of the 7 planned match dimensions), and
  **per-position email drafting**.
- The **Identity Engine does not exist**, the **Intelligence Engine is
  single-dimensional**, there is **no database**, no **scheduler**, no **API**,
  no **digest**, no **tracking**, and the code is a **monolith**.
- Milestone mapping follows `docs/04` exactly: Phase 1 refactor → Phase 2
  profile → Phase 3 DB → Phase 4 matching → Phase 5 email → Phase 6 API →
  Month 2 dashboard/tracking.

## A. Existing (fully covered)

| Requirement | Where | Notes |
|---|---|---|
| Deterministic ranking | `score_relevance`/`is_relevant` (tiered taxonomy, weights, threshold) | LLM-independent core scoring ✔ |
| Opportunity discovery (positions) | 13 `@register_source` boards + `seed_urls` + `uni_departments` | EURAXESS, Nature, jobs.ac.uk, FindAPhD, AJO, AAS, JREC-IN, ESO, ESA, AcademicTransfer, LinkedIn, dept sweeps |
| Supervisor discovery | OpenAlex (any major, no token), NASA ADS, arXiv; author-direct + keyword paths | Writes `supervisors_<field>_<country>.*` |
| Normalization | `make_record` + `OUTPUT_FIELDS` (16-col schema), canonical countries, URL normalize | Defensive; every field optional |
| Deduplication | `dedupe_records` (URL pass + title/institution pass + merge) | |
| Freshness/expiry | `apply_freshness` (deadline → posted → first_seen → page_date), state file | |
| Geo filter | country map/aliases/guess + `country_allowed` | Filter only (not a score) |
| Position-type gate | `classify_position_type` (phd/postdoc/faculty/staff/unknown) | |
| Multi-field extensibility | 10 profiles + `template.yaml` + `--new-field` wizard; YAML-only | |
| Source/field contracts | `CONTRIBUTING.md` (`@register_source`, `@seed_adapter`) | |
| Emails (drafts) | `build_email`/`write_emails` per position | Partial basis for digest |
| Dashboard (static) | self-contained HTML (results + supervisors) | No server; regenerated per run |
| Network resilience | proxy auto-detect, anti-bot chain (curl_cffi/Playwright), robots, throttle, retry | |
| NFR: low budget | SQLite-planned, free APIs (OpenAlex), tokenless paths | |
| NFR: deterministic, LLM-independent scoring | yes | |
| NFR: beginner-friendly config | YAML + wizard + commented template | |

## B. Partially implemented

| PRD / Arch requirement | What exists | What's missing for v1 |
|---|---|---|
| Opportunity matching, **ranked by fit** | relevance_score = topic dimension only | 6 more dimensions (skill/method/advisor/location/funding/competitiveness) — `specs/02` |
| Matching: **labs / institutions** | `uni_departments` source + institution field | Lab-level matching, per-lab openings feed |
| Matching: **funded openings** | curated static `SCHOLARSHIPS` list | Funded-opening discovery + funding-fit scoring |
| Explainability | `matched_anchors`, `relevance_score`, tailored email fit-paragraph | "what's missing", "why a good next step", confidence indicator |
| Email → **weekly digest** | per-position email files | digest aggregation, cap (≤5+5), schedule, next-action field, only-high-fit gate (specs/03: >85) |
| Ranking | single pass on results | deterministic multi-dim weighted engine (specs/02) |
| Knowledge Engine | batch, manual-run crawl | **continuous** discovery (scheduler), persistent store, topic/institution normalization |
| Data model | ad-hoc `dict` records (`OUTPUT_FIELDS`) | DB entities: Opportunity, Supervisor, Match, Application, Bookmark, DigestPreference |
| Method/topic fit | `context_terms` ≈ methods; `core_anchors` ≈ topics | structured skills/methods/tools fields with confidence |
| Tests | `--self-test` (~100 asserts) + `test_supervisors.py` network sweep | per-module unit tests (Phase 1) |
| Modular code | single 7,368-line file | module structure (Phase 1) |

## C. Missing — per-component estimates

| # | Component (v1) | Complexity | Risk | Dependencies | Recommended milestone |
|---|---|---|---|---|---|
| 1 | **Module refactor** of the monolith (core/pipeline/sources/toolkit/supervisors + per-module tests) | M | M — behavior drift | none (pure relocation) | Phase 1 (Month 1) |
| 2 | **User intake** (paste bio/CV, optional ORCID/Scholar/LinkedIn/site, field/region/funding choices) | S | L | profile engine | Phase 2 (Month 1) |
| 3 | **Profile engine / Identity Engine** (CV text → `UserProfile` dataclass; Pydantic; every field has confidence; unknown = null) | M | M — LLM-extraction quality + provider decision | LLM provider decision (none in repo today) | Phase 2 (Month 1) |
| 4 | **Opportunity DB** (SQLAlchemy + SQLite; Opportunity/Supervisor entities; indexes; migration strategy) | M | M — schema lock-in | Module refactor (#1) | Phase 3 (Month 1) |
| 5 | **Deterministic matching engine** (7 dimensions, weights 30/20/15/15/10/5/5; each score independently testable; no LLM ranking) | M | M — weight tuning | Profile engine (#3), DB (#4), taxonomy from refactor (#1) | Phase 4 (Month 1) |
| 6 | **Explainability layer** ("why it matches", "what's missing", "why a good next step", confidence) | M | M — requires LLM drafting + deterministic inputs | Matching engine (#5), LLM layer | Phase 4 (Month 1) |
| 7 | **Email digest service** (weekly default; ≤5 positions + ≤5 supervisors; only >85; include deadline/funding/next action) | M | M — deliverability, scheduling | Matching engine (#5) | Phase 5 (Month 1) |
| 8 | **Scheduler** for continuous knowledge-engine discovery (cron/APScheduler) | S | L | Refactor (#1) so `run()` is callable | Phase 5 / Month 2 |
| 9 | **REST API** (FastAPI + OpenAPI; POST /profile, GET /matches, /supervisors, /opportunities, POST /bookmark, /feedback, /email_preferences) | M | L | DB (#4), matching (#5) | Phase 6 (Month 1) |
| 10 | **Shortlist tracking** (statuses: saved → contacted → applied → interview → rejected → accepted) | M | L | DB (#4), API (#9) | Month 2 |
| 11 | **Bookmark system** | S | L | DB (#4), API (#9) | Month 2 |
| 12 | **Feedback capture + storage** | S | L | DB (#4), API (#9) | Month 2 |
| 13 | **Auth + per-user data separation** | M | **H** — security-sensitive | API (#9), DB (#4) | Month 2 (required before private beta, Month 4) |
| 14 | **Frontend dashboard** (Next.js/Tailwind/shadcn) | L | M — scope creep, designer/UX | API (#9) | Month 2 |
| 15 | **LLM integration layer** (extraction, summarization, explanation drafting; provider-independent) | M | M — vendor lock-in risk (docs/06: no single-provider dependence) | Provider decision (ask founder) | Phase 2 (extraction) / Phase 4 (explanation) |
| 16 | **Topic + institution normalization** (knowledge graph: dedupe institutions, canonical topics) | M | L | DB (#4) | Month 3 |
| 17 | **More sources + dedupe reliability** | S–M | L | Refactor (#1) | Month 3 |
| 18 | **Funding-fit data** (structured funding status per opportunity) | M | **H** — data availability across boards | Matching (#5), DB (#4) | Month 3–4 |
| 19 | **Competitiveness scoring** (deterministic rule-based first; e.g. institution tier/funding type) | L | **H** — data availability; must stay deterministic (docs/06) | Matching (#5) | Month 3–4 |

## D. Future (beyond v1)

| Item | Trigger / Roadmap |
|---|---|
| Feedback-driven / learned ranking tuning | Month 6 (only after real feedback per `docs/04`) |
| Expand from PhD-only to broader career roles | Month 6 |
| Public free launch, donation support, onboarding | Month 5 |
| Multi-AI-model support (model-agnostic routing) | Post-launch hardening |
| Scale to ~1M users (queueing, cache, workers, sharding) | Post-launch (Kimi critique territory) |
| Social network / marketplace / generic search | Explicitly **not** v1 (`docs/01`) |
| Digest A/B testing & recommendation evaluation | Month 4 (private beta) |

## E. Requirement-level coverage map

**PRD (functional)**
- User intake — **Missing** (#2, Phase 2)
- Profile extraction (domain/subfield/methods/tools/skills/level/roles/regions/funding/constraints/confidence) — **Missing** (#3, Phase 2)
- Opportunity matching (positions/supervisors/labs/funded/ranked) — **Partial** (#5, Phase 4)
- Explainability (why/what's missing/next step/confidence) — **Partial** (#6, Phase 4)
- Email digest — **Partial** (#7, Phase 5)
- Tracking — **Missing** (#10, Month 2)

**PRD (non-functional)**
- Low budget — **Existing** · Deterministic ranking — **Existing** · LLM-independent scoring — **Existing**
- Modular code — **Missing** (#1, Phase 1) · Easy to expand — **Existing/Partial**

**Architecture v1**
- Knowledge Engine — **Partial** (crawler exists; scheduler, DB, normalization missing)
- Identity Engine — **Missing** (#3, Phase 2)
- Intelligence Engine — **Partial** (relevance only → #5, Phase 4)
- Data flow: ingest/normalize **Existing**; profile **Missing**; score **Partial**; explain **Partial**; digest **Missing**; feedback **Missing**
- Stack: Python **Existing**; FastAPI/SQLite/SQLAlchemy **Missing**; Next.js/Tailwind/shadcn **Missing** (Month 2)
- Data model: UserProfile/DB entities **Missing** (#3/#4)
- Matching dimensions (specs/02): topic **Partial**; method/skill/experience/funding/competitiveness **Missing**

## F. Critical-path notes

1. **#1 refactor gates everything else** (DB, scheduler, API all call into the
   pipeline) — do it first, per `docs/04` Phase 1 and the release rule.
2. **LLM provider decision is the #1 open dependency** — profile extraction and
   explanation drafting both assume an LLM, and `docs/06` forbids single-provider
   lock-in. See QUESTIONS_FOR_FOUNDER.md.
3. **Competitiveness & funding data (#18/#19) are the highest-risk items** —
   neither source exists today; plan deterministic placeholders in Phase 4 and
   revisit with real data in Months 3–4.
4. **Auth (#13) is the only High-risk security item** — schedule early in Month 2
   since private beta (Month 4) needs per-user state.
