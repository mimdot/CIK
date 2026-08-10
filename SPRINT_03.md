# Sprint 03: Finish Migration + Build Matching Engine + Wire End-to-End

**Duration:** Weeks 5-6 (2026-08-04 → 2026-08-17)
**Goal:** Complete Phase 1 migration (Steps 9-12), build the 3-dimension matching engine, and wire the full flow: paste CV → extract profile → run pipeline → match → explain → write results

---

## What shipped in Sprints 01-02 (for context)

| Item | Status |
|------|--------|
| Migration Steps 1-8 (config, utils, records, taxonomy, http, sources, pipeline) | DONE |
| Profile engine (LLM + schema + extraction) | BUILT (not wired to CLI) |
| Database (7 models + repos + seed) | BUILT (not wired to pipeline) |
| Monolith: 7,368 → 2,884 lines | DONE |
| Tests: 153 passing | DONE |
| 18 sources registered, self-test passes | DONE |

---

## Track A: Finish Migration (Weeks 5-6, low risk)

### S9: Extract `supervisors/`
**Effort:** 1-2 days
**Risk:** Medium — complex aggregation logic

Move from `phd_aggregator.py` to `supervisors/`:
- `aggregate_supervisors()` + name-variant merge logic
- `ads_supervisor_docs()`, `arxiv_supervisor_docs()`
- `openalex_supervisor_docs()`, `openalex_supervisor_authors()`
- `_openalex_author_recent()`, `_openalex_works_pool()`, `_openalex_author_records()`
- `_author_current_institution()`
- `_supervisor_chain()`, `_supervisor_focus()`
- `find_supervisors()` (the CLI entry point)
- `write_supervisors_html()`
- `_orcid_public_email()`
- `AUTHOR_SEARCH_FMT`, `SOURCE_LABELS`, `ARXIV_API`

**Re-export:** `phd_aggregator.py` re-imports `find_supervisors`, `aggregate_supervisors`, and all public names for back-compat.

### S10: Extract `toolkit/`
**Effort:** 1 day
**Risk:** Low

Move to `toolkit/`:
- `build_email()`, `write_emails()`, `_EMAIL_FIT_RULES`, `_EMAIL_FIT_FALLBACK`
- `find_professors()`, `PROFESSOR_SEED`
- `write_scholarships()`, `SCHOLARSHIPS`, `_SCHOLARSHIP_PRACTICAL_NOTES`
- `APPLICANT_PROFILE`, `_ensure_applicant_profile()`
- `_slugify()`

### S11: Slim `phd_aggregator.py` to CLI entry point
**Effort:** 0.5 days
**Risk:** Low

After S9+S10, the monolith should contain only:
- Imports + back-compat re-exports (~50 lines)
- `parse_args()` + CLI argument definitions
- `main()` orchestration
- `if __name__ == "__main__"` block

Target: **~500-800 lines** (down from 2,884).

### S12: Full test suite
**Effort:** 1 day
**Risk:** Medium

Add missing test coverage:
- `tests/test_supervisors_unit.py` — unit tests for aggregation, name merge, country filter (mock HTTP)
- `tests/test_toolkit.py` — email builder, slugify, professor list, scholarships
- `tests/test_cli.py` — argument parsing, `--list-sources`, `--list-fields`, `--self-test` invocation
- Verify every module has a corresponding test file

**Gate:** `--self-test` passes. `python -m pytest tests/ -q` passes with 200+ tests.

---

## Track B: Matching Engine (Weeks 5-6, new feature)

### B1: Design matching interface
**Effort:** 0.5 days
**Deliverable:** `matching/__init__.py` + `matching/scorer.py`

```python
# matching/scorer.py
from core.profile_schema import UserProfile

class MatchResult:
    overall_score: float
    topic_score: float
    method_score: float
    location_score: float
    explanation: str        # "why this match, what's missing"
    confidence: float

def score_match(profile: UserProfile, opportunity: dict) -> MatchResult:
    """Score a single opportunity against a user profile. Deterministic, no LLM."""
    ...
```

### B2: Implement topic dimension
**Effort:** 1 day
**Reuses:** `core/taxonomy.score_relevance()` (already exists)

The existing `score_relevance` scores an opportunity's title+description against a taxonomy. For matching, we need the inverse: how well does an opportunity's topic match the profile's domain/subfield.

```python
def topic_score(profile: UserProfile, opportunity: dict, cfg: Config) -> float:
    """0-1 score: how well the opportunity's topic matches the profile."""
    # Use profile.domain + profile.subfield to create a mini-taxonomy
    # Score the opportunity against it with score_relevance
    # Normalize to 0-1
```

### B3: Implement method dimension
**Effort:** 0.5 days

```python
def method_score(profile: UserProfile, opportunity: dict) -> float:
    """0-1 score: overlap between profile methods/tools and opportunity requirements."""
    # Extract methods/tools from opportunity description (keyword match)
    # Compare against profile.methods + profile.tools
    # Jaccard-like overlap, normalized
```

### B4: Implement location dimension
**Effort:** 0.5 days

```python
def location_score(profile: UserProfile, opportunity: dict) -> float:
    """0-1 score: does the opportunity's country match profile preferences."""
    # 1.0 if country in profile.countries_preferred
    # 0.5 if profile has no preference (empty list)
    # 0.0 if country is in profile.constraints (anti-preference)
```

### B5: Explainability generator
**Effort:** 1 day

```python
def explain_match(profile: UserProfile, opportunity: dict, scores: dict) -> str:
    """Generate a human-readable explanation of why this opportunity matches."""
    parts = []
    if scores["topic_score"] > 0.7:
        parts.append(f"Strong topic match: your {profile.domain}/{profile.subfield} aligns with this position.")
    elif scores["topic_score"] > 0.4:
        parts.append(f"Partial topic match: related to your {profile.domain} background.")
    else:
        parts.append("Weak topic match — this position is outside your primary field.")
    # ... method, location, missing skills
    return " ".join(parts)
```

### B6: Integration — wire matching into pipeline
**Effort:** 1 day

In `pipeline/run.py`, after dedup + sort:
```python
# For each opportunity, score against the active profile
if profile:
    for opp in deduped:
        result = score_match(profile, opp, cfg)
        opp["match_score"] = result.overall_score
        opp["match_explanation"] = result.explanation
    deduped.sort(key=lambda r: -(r.get("match_score") or r.get("relevance_score", 0)))
```

### B7: Test suite for matching
**Effort:** 0.5 days

- `tests/test_matching.py` with golden-set fixtures:
  - High-match opportunity (same domain, same methods, preferred country) → score > 0.8
  - Low-match opportunity (different domain, different country) → score < 0.3
  - Edge case: profile with empty methods → method_score returns 0.5 (neutral)
  - Edge case: opportunity with no country → location_score returns 0.5 (neutral)
  - Explanation string contains domain name and methods

---

## Track C: CLI Wiring (Week 6)

### C1: Add `--build-profile` CLI flag
**Effort:** 0.5 days

```bash
python phd_aggregator.py --build-profile "Mohammad is a PhD student in astronomy..."
```

This calls `extract_profile()` → saves to DB via `ProfileRepo.create()` → prints the extracted profile.

### C2: Add `--seed-db` CLI flag
**Effort:** 0.5 days

```bash
python phd_aggregator.py --seed-db phd_positions.json
```

This calls `seed_from_json()` → prints record count.

### C3: Wire `--run` to match when profile exists
**Effort:** 0.5 days

When a profile exists in the DB, `--run` scores each opportunity against it and includes `match_score` + `match_explanation` in the output.

### C4: Add `--show-profile` CLI flag
**Effort:** 0.25 days

Prints the active profile from the DB.

---

## Definition of Done

| Item | Done when |
|------|-----------|
| S9 (supervisors extraction) | `supervisors/` exists, `--self-test` passes, `--find-supervisors` works |
| S10 (toolkit extraction) | `toolkit/` exists, `--self-test` passes, `--write-emails` works |
| S11 (CLI slim) | `phd_aggregator.py` is ~500-800 lines, only CLI logic |
| S12 (full test suite) | 200+ tests, every module has a test file |
| B1-B5 (matching engine) | `matching/` package with 3 dimensions + explainability, all tested |
| B6 (pipeline integration) | `--run` with active profile produces match scores |
| B7 (matching tests) | Golden-set tests pass, edge cases covered |
| C1-C4 (CLI wiring) | `--build-profile`, `--seed-db`, `--show-profile` all work |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| S9 supervisor extraction breaks aggregation | Mock HTTP in unit tests; compare output against pinned test fixtures |
| B2 topic scoring doesn't match expectations | Use existing self-test assertions as golden set; compare old vs new scores |
| B5 explainability is generic/useless | Start with template-based explanations; iterate based on manual review |
| C3 --run + profile integration changes output | Pin current self-test output before integration; compare byte-for-byte |

---

## Sprint 03 Prompt (for next session)

```
Read these files first:
1. /home/mohammad-reza/career_intelligence_kit/SPRINT_03.md
2. /home/mohammad-reza/career_intelligence_kit/MIGRATION_PLAN.md
3. /home/mohammad-reza/career_intelligence_kit/core/profile_schema.py (already read)
4. /home/mohammad-reza/career_intelligence_kit/specs/05_V1_Database_Schema.md

Then execute Sprint 03 from SPRINT_03.md, in this order:

TRACK A — FINISH MIGRATION (do one step at a time, run --self-test after each):

9. Step S9: Extract supervisors/ package. Move aggregate_supervisors, ads_supervisor_docs, arxiv_supervisor_docs, openalex_supervisor_docs, openalex_supervisor_authors, _openalex_author_recent, _openalex_works_pool, _openalex_author_records, _author_current_institution, _supervisor_chain, _supervisor_focus, find_supervisors, write_supervisors_html, _orcid_public_email, AUTHOR_SEARCH_FMT, SOURCE_LABELS, ARXIV_API. Re-export from phd_aggregator.py. --self-test passes.

10. Step S10: Extract toolkit/ package. Move build_email, write_emails, _EMAIL_FIT_RULES, _EMAIL_FIT_FALLBACK, find_professors, PROFESSOR_SEED, write_scholarships, SCHOLARSHIPS, _SCHOLARSHIP_PRACTICAL_NOTES, APPLICANT_PROFILE, _ensure_applicant_profile, _slugify. Re-export from phd_aggregator.py. --self-test passes.

11. Step S11: Slim phd_aggregator.py to ~500-800 lines. Should contain only: imports + re-exports, parse_args(), main(), __name__ block. All logic is in packages.

12. Step S12: Add tests/test_supervisors_unit.py (mock HTTP, test aggregation/name merge/country filter), tests/test_toolkit.py (email builder, slugify), tests/test_cli.py (arg parsing). Target: 200+ tests total.

TRACK B — MATCHING ENGINE (new feature, parallel with Track A):

13. B1: Create matching/ package with __init__.py and scorer.py. Define MatchResult dataclass and score_match(profile, opportunity) interface.

14. B2: Implement topic_score(profile, opportunity, cfg) using score_relevance. Normalize to 0-1. Test with fixture opportunities.

15. B3: Implement method_score(profile, opportunity) using Jaccard overlap of profile.methods+tools vs opportunity description keywords. Test.

16. B4: Implement location_score(profile, opportunity) using profile.countries_preferred vs opportunity country. Test.

17. B5: Implement explain_match(profile, opportunity, scores) generating human-readable text. Test.

18. B6: Wire matching into pipeline/run.py — when profile exists, score each opportunity and add match_score + match_explanation to output. --self-test still passes.

19. B7: Create tests/test_matching.py with golden-set fixtures: high-match, low-match, edge cases (empty methods, no country), explanation content checks.

TRACK C — CLI WIRING (after Track A completes):

20. C1: Add --build-profile "CV text" flag to parse_args(). Calls extract_profile() → saves to DB → prints result.

21. C2: Add --seed-db path flag. Calls seed_from_json() → prints count.

22. C3: Modify --run to check for active profile in DB. If found, score each opportunity against it and include match_score in output.

23. C4: Add --show-profile flag. Prints active profile from DB.

RULES:
- Preserve every feature. No optimization during extraction.
- --self-test must pass after every migration step.
- Ranking stays deterministic. LLM stays out of scoring.
- LLM is only used in core/profile.py (extraction).
- Matching engine is pure Python, no LLM, no network.
- Each new module gets a pytest file in tests/.
- The monolith re-imports everything for back-compat.
```
