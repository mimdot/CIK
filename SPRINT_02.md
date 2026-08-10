# Sprint 02: Migration Continuation + Phase 2-3 Kickoff

**Duration:** Weeks 3-4 (2026-08-04 → 2026-08-17)
**Goal:** Finish Phase 1 Steps 5-8, start Phase 2 (profile engine) and Phase 3 (database implementation)

---

## What shipped in Sprint 01 (for context)

| Item | Status |
|------|--------|
| Migration Steps 2-4 (utils, records, taxonomy, http) | DONE |
| academictransfer `_pw_browser()` bug | FIXED |
| `.gitignore` + `vpn.txt` removal | DONE |
| LLM provider decision | DONE (LiteLLM + OpenAI + Ollama) |
| Database schema spec | DONE (7 tables, SQLite) |
| Source health audit | DONE (13 sources tested) |
| 85 tests passing | DONE |

---

## Track A: Migration (Weeks 3-4, primary)

### S5: Move sources to `sources/` in batches
**Effort:** 3-4 days
**Risk:** Medium — each source is fragile, but they're well-isolated

Move in 3 batches to keep `--self-test` passing after each:

**Batch A (feed/simple HTML — lowest risk):**
- `source_eso` → `sources/eso.py`
- `source_esa` → `sources/esa.py`
- `source_jrecin` → `sources/jrecin.py`
- `source_academicjobsonline` → `sources/academicjobsonline.py`

**Batch B (HTML with pagination):**
- `source_euraxess` + `_euraxess_card` → `sources/euraxess.py`
- `source_nature_careers` → `sources/nature_careers.py`
- `source_jobs_ac_uk` → `sources/jobs_ac_uk.py`

**Batch C (JS/Playwright + complex):**
- `source_findaphd` → `sources/findaphd.py`
- `source_academictransfer` + `_academictransfer_ssr_fallback` → `sources/academictransfer.py`
- `source_aas` → `sources/aas.py`
- `source_linkedin` + `_linkedin_card` → `sources/linkedin.py`
- `source_uni_departments` + `UNIVERSITY_DEPARTMENTS` registry → `sources/uni_departments.py`
- `source_seed_urls` + `discover_siblings` + seed adapters → `sources/seed_urls.py`
- Stub sources (`iau`, `astrobetter`, `china`, `korea`, `new_zealand`) → `sources/stubs.py`

**After each batch:** `--self-test` must pass. Run `--source <name>` for each moved source to verify no import breakage.

**Re-export pattern:** `phd_aggregator.py` re-imports all source functions and `SOURCES` dict so `test_supervisors.py` and external importers keep working.

### S6: Extract `pipeline/parse_page.py`
**Effort:** 1 day
**Risk:** Low

Move from `phd_aggregator.py`:
- `parse_position_page()` (JSON-LD, OpenGraph, readability extraction)
- `_iter_jsonld_objects()`
- `_seed_adapter` decorator + `SEED_ADAPTERS` registry
- `_parent_listing_candidates()`, `_seed_sibling_pattern()`
- `extract_page_date()` + `_POSTED_LINE_RE`

### S7: Extract `pipeline/filter.py` + `pipeline/dedupe.py` + `pipeline/freshness.py`
**Effort:** 2 days
**Risk:** Medium — filtering and freshness affect recall

Move to `pipeline/filter.py`:
- `filter_records()`

Move to `pipeline/dedupe.py`:
- `dedupe_records()`, `_merge_into()`, `_FRESHNESS_QUALITY`

Move to `pipeline/freshness.py`:
- `apply_freshness()`, `load_state()`, `save_state()`

**Gate:** `--self-test` passes. The self-test exercises filter, dedupe, and freshness extensively — this is the critical check.

### S8: Extract `pipeline/run.py`
**Effort:** 1 day
**Risk:** Low

Move to `pipeline/run.py`:
- `run()` (orchestration: sources → filter → freshness → dedupe → sort → mark_new → write → summary)
- `sort_key()`, `load_previous_keys()`, `mark_new()`
- `write_outputs()`, `write_html()`, `_HTML_TEMPLATE`
- `print_summary()`

**After S5-S8:** The monolith should be ~2,500-3,000 lines (down from 5,473), containing only: imports, back-compat re-exports, source registry, CLI, and career toolkit functions.

---

## Track B: Phase 2 — Profile Engine (Weeks 3-4, parallel)

### B1: Build `core/llm.py` (LiteLLM wrapper)
**Effort:** 1-2 days
**Depends on:** LLM provider decision (done)

Implement:
```python
# core/llm.py
class LLMRouter:
    """Provider-agnostic LLM interface via LiteLLM."""
    def __init__(self, default_model: str, fallback_model: str): ...
    def complete(self, prompt: str, schema: dict | None = None) -> str: ...
    # Wraps litellm.completion() with retry + fallback logic
```

Config in `core/config.py`:
- `LLM_DEFAULT = "openai/gpt-4o-mini"`
- `LLM_FALLBACK = "ollama/llama3.1:8b"`

Install: `pip install litellm`

### B2: Design `UserProfile` Pydantic model
**Effort:** 0.5 days
**Deliverable:** `core/profile_schema.py`

```python
from pydantic import BaseModel, Field

class UserProfile(BaseModel):
    domain: str
    subfield: str | None = None
    methods: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience_level: str  # "phd_student" | "postdoc" | "faculty" | ...
    target_roles: list[str] = Field(default_factory=list)
    countries_preferred: list[str] = Field(default_factory=list)
    funding_requirement: str | None = None
    constraints: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str  # original input
```

### B3: Build profile extraction prompt + `core/profile.py`
**Effort:** 2 days
**Depends on:** B1 + B2

```python
# core/profile.py
def extract_profile(raw_text: str, llm: LLMRouter) -> UserProfile:
    """Extract a structured UserProfile from CV/bio text using LLM."""
    # 1) Prompt with schema instructions
    # 2) llm.complete(prompt, schema=UserProfile.model_json_schema())
    # 3) Validate with Pydantic; retry once on failure
    # 4) Return validated UserProfile
```

**Test:** Unit test with fixture CV text → assert profile fields. Mock the LLM for offline testing.

---

## Track C: Phase 3 — Database Implementation (Weeks 3-4, parallel)

### C1: Implement SQLAlchemy models
**Effort:** 1 day
**Depends on:** specs/05_V1_Database_Schema.md (done)

Create `db/models.py` with all 7 tables from the schema spec. Use SQLAlchemy 2.0 declarative style.

### C2: Database initialization + seed
**Effort:** 1 day
**Depends on:** C1

- `db/init.py`: create engine, create tables, seed from existing `phd_positions.json`
- Seed function reads the current JSON output and inserts into `opportunities` table
- Verify: `SELECT count(*) FROM opportunities` matches JSON record count

### C3: Repository pattern
**Effort:** 1 day
**Depends on:** C1

Create `db/repositories.py` with:
- `OpportunityRepo` (upsert, search, get_by_id)
- `ProfileRepo` (create, get_active, update)
- `MatchRepo` (upsert, get_by_profile)

Each repo is a thin wrapper over SQLAlchemy sessions. No business logic in repos.

---

## Definition of Done

| Item | Done when |
|------|-----------|
| S5 (source migration) | All 14 sources in `sources/`, `--self-test` passes, each source runs with `--source X` |
| S6 (parse_page extraction) | `pipeline/parse_page.py` exists, `--self-test` passes |
| S7 (filter/dedupe/freshness) | Three pipeline modules exist, `--self-test` passes |
| S8 (run extraction) | `pipeline/run.py` exists, monolith is ~3,000 lines, `--self-test` passes |
| B1 (LLM wrapper) | `core/llm.py` exists, `litellm` in requirements, unit test passes with mock |
| B2 (UserProfile schema) | `core/profile_schema.py` exists, Pydantic validates fixture data |
| B3 (profile extraction) | `core/profile.py` exists, extracts profile from fixture CV text (mocked LLM), test passes |
| C1 (SQLAlchemy models) | `db/models.py` exists, all 7 tables created on `init_db()` |
| C2 (seed) | `db/init.py` seeds from JSON, record count matches |
| C3 (repositories) | `db/repositories.py` exists, CRUD ops work against test DB |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| S5 source migration breaks parsing | Run `--source X` after each batch; compare record counts against SOURCE_HEALTH.md baseline |
| S7 filter/freshness extraction changes recall | Pin self-test assertions before extraction; compare output byte-for-byte |
| B1 LiteLLM install fails in Iran | Test with `ollama` backend first (works offline); cloud backend is secondary |
| B3 LLM extraction quality is poor | Start with simple fields (domain, subfield, methods); add complexity iteratively |
| C2 seed from JSON fails on schema mismatch | Map OUTPUT_FIELDS → Opportunity columns explicitly; test with 10-record fixture first |

---

## Sprint 02 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_02.md
2. /home/mohammad-reza/career_intelligence_kit/MIGRATION_PLAN.md
3. /home/mohammad-reza/career_intelligence_kit/specs/05_V1_Database_Schema.md
4. /home/mohammad-reza/career_intelligence_kit/docs/07_LLM_Provider_Decision.md

Then execute Sprint 02 from SPRINT_02.md, in this order:

TRACK A — MIGRATION (do one step at a time, run --self-test after each):

5. Step S5: Move sources to sources/ in 3 batches.
   Batch A (lowest risk): source_eso, source_esa, source_jrecin, source_academicjobsonline -> sources/
   Batch B (HTML): source_euraxess + _euraxess_card, source_nature_careers, source_jobs_ac_uk -> sources/
   Batch C (JS/complex): source_findaphd, source_academictransfer + SSR fallback, source_aas, source_linkedin + _linkedin_card, source_uni_departments + UNIVERSITY_DEPARTMENTS, source_seed_urls + discover_siblings + seed adapters, stub sources -> sources/
   After each batch: --self-test passes, --source <name> works for each moved source. Re-export all source functions and SOURCES dict from phd_aggregator.py for back-compat.

6. Step S6: Extract pipeline/parse_page.py. Move parse_position_page, _iter_jsonld_objects, _seed_adapter + SEED_ADAPTERS, _parent_listing_candidates, _seed_sibling_pattern, extract_page_date, _POSTED_LINE_RE. --self-test passes.

7. Step S7: Extract pipeline/filter.py, pipeline/dedupe.py, pipeline/freshness.py. Move filter_records, dedupe_records, _merge_into, _FRESHNESS_QUALITY, apply_freshness, load_state, save_state. --self-test passes.

8. Step S8: Extract pipeline/run.py. Move run, sort_key, load_previous_keys, mark_new, write_outputs, write_html, _HTML_TEMPLATE, print_summary. --self-test passes. Monolith should be ~3,000 lines.

TRACK B — PROFILE ENGINE (parallel with Track A):

9. B1: Build core/llm.py (LLMRouter wrapping litellm). Install litellm. Config: LLM_DEFAULT="openai/gpt-4o-mini", LLM_FALLBACK="ollama/llama3.1:8b". Unit test with mock.

10. B2: Design UserProfile Pydantic model in core/profile_schema.py. Fields: domain, subfield, methods, tools, skills, experience_level, target_roles, countries_preferred, funding_requirement, constraints, confidence, raw_text. Test with fixture data.

11. B3: Build core/profile.py with extract_profile(raw_text, llm) -> UserProfile. Prompt engineering for CV extraction. Pydantic validation + retry on failure. Unit test with mocked LLM returning fixture JSON.

TRACK C — DATABASE (parallel with Track A):

12. C1: Create db/models.py with all 7 SQLAlchemy 2.0 models from specs/05_V1_Database_Schema.md. Test: init_db() creates all tables.

13. C2: Create db/init.py with seed function that reads phd_positions.json and inserts into opportunities table. Verify record count matches.

14. C3: Create db/repositories.py with OpportunityRepo, ProfileRepo, MatchRepo. Thin wrappers over SQLAlchemy sessions. Test CRUD against test DB.

RULES:
- Preserve every feature. No optimization during extraction.
- --self-test must pass after every migration step.
- Ranking stays deterministic. LLM stays out of scoring.
- LLM is only used in core/profile.py (extraction), core/llm.py (wrapper).
- Each extracted module gets a pytest file in tests/.
- The monolith re-imports everything for back-compat.
```
