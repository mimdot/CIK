# Sprint 01: Foundation Fix + Migration Continuation

**Duration:** Weeks 1-2 (2026-08-02 → 2026-08-16)
**Goal:** Clear remaining blockers, advance migration to Step 4, start parallel design work

---

## Blockers to Clear First (Day 1-2)

### B1: Fix `academictransfer` source — `_pw_browser()` bug
**Severity:** Critical (source is silently broken)
**File:** `phd_aggregator/phd_aggregator.py:1710`
**Issue:** `http._pw_browser(pw, headless=True)` calls a method that doesn't exist on `Http`. The Playwright interception path always throws `AttributeError` and falls back to SSR.
**Fix:** Replace with the correct pattern — either use `http._pw_ensure()` + `http._pw_ctx.new_page()` (the shared persistent context), or refactor to match the `Http` class's actual API. The `academictransfer` source should use the same persistent browser context that `findaphd` and `aas` use.
**Test:** Run `python phd_aggregator.py --source academictransfer --list-sources` to verify no `AttributeError`.

### B2: Remove `vpn.txt` from working tree
**Severity:** Critical (live credential on disk)
**File:** `phd_aggregator/vpn.txt`
**Action:** `rm phd_aggregator/vpn.txt` — already gitignored, but the file should be deleted from the working tree. If the VPN instructions are valuable, rewrite them without the subscription URL.

### B3: Verify `.gitignore` completeness
**Severity:** Medium (data leak prevention)
**Check:** Ensure `.gitignore` covers all of: `applicant.yaml`, `vpn.txt`, `.env`, `.seen_positions.json`, `__pycache__/`, `*.pyc`, `*.egg-info/`, `phd_positions_*.json`, `phd_positions_*.csv`, `phd_positions_*.html`, `.pw_profile/`, `emails/`

---

## Migration Steps (Week 1-2, primary track)

### S2: Extract `core/utils.py` + `core/records.py`
**Effort:** 1-2 days
**Risk:** Low

Move from `phd_aggregator.py` to `core/utils.py`:
- `_strip_html()`, `clean_oneline()`, `clean_text()`
- `normalize_url()`, `_key_text()`, `dedupe_key()`
- `parse_date()`, `_month_num()`, `_DATE_FORMATS`, `_DATE_EXTRACT`
- `canonical_country()`, `guess_country()`, `CITY_HINTS`, `_CITY_LOOKUP`

Move to `core/records.py`:
- `make_record()` and `OUTPUT_FIELDS`

**Gate:** `--self-test` passes, `tests/test_config.py` passes, new `tests/test_utils.py` with:
- `test_normalize_url_strips_tracking_params`
- `test_normalize_url_lowercases_host`
- `test_dedupe_key_prefers_title_institution`
- `test_parse_date_iso`
- `test_parse_date_european`
- `test_parse_date_struct_time`
- `test_canonical_country_iso2`
- `test_canonical_country_alias`
- `test_guess_country_city_hint`
- `test_make_record_defensive`

### S3: Extract `core/taxonomy.py`
**Effort:** 2-3 days
**Risk:** HIGH — scoring correctness is the core value proposition

Move from `phd_aggregator.py` to `core/taxonomy.py`:
- `_compile_term()`, `compile_taxonomy()` (already in `core/config.py`, re-home here)
- `score_relevance()`, `is_relevant()`
- `_TYPE_PATTERNS`, `_TYPE_REGEX`, `_TYPE_PRIORITY`, `_match_type()`, `classify_position_type()`
- `_PHD_REQUIREMENT_NOISE`
- `country_allowed()`

**Gate:** `--self-test` passes (this is the critical check — the self-test exercises scoring extensively). Add `tests/test_taxonomy.py` with:
- `test_score_relevance_core_in_title_high_score`
- `test_score_relevance_core_in_desc_lower_score`
- `test_score_relevance_context_only_no_anchor`
- `test_score_relevance_negative_deducted`
- `test_score_relevance_negative_skipped_when_title_anchor`
- `test_is_relevant_requires_anchor`
- `test_is_relevant_requires_threshold`
- `test_require_title_anchor_blocks_desc_only`
- `test_classify_position_type_phd`
- `test_classify_position_type_postdoc_not_leaked`
- `test_classify_position_type_unknown`

### S4: Extract `core/http.py`
**Effort:** 2-3 days
**Risk:** Medium — anti-bot chain is complex but well-isolated

Move to `core/http.py`:
- `RobotsCache` class
- `Http` class (all methods)
- `BROWSER_HEADERS`, `_CHALLENGE_RE`, `_STEALTH_JS`
- `detect_proxy()`, `_proxy_reachable()`, `_probe_proxy()`, `_direct_online()`
- `PROXY_CANDIDATES`, `PROBE_URL`, `PROBE_TIMEOUT`

**Gate:** `--self-test` passes. Integration test with a single known-good source (`--source eso` — ESO RSS, no anti-bot needed).

---

## Parallel Track: Design Work (can start Week 1)

### D1: LLM Provider Evaluation
**Effort:** 1 day research + founder discussion
**Deliverable:** Decision document in `docs/07_LLM_Provider_Decision.md`

Evaluate:
1. **OpenAI API** — GPT-4o-mini for extraction, GPT-4o for explanation. ~$0.15/1M input tokens.
2. **Anthropic API** — Claude 3.5 Haiku for extraction, Sonnet for explanation. ~$0.80/1M input tokens.
3. **Ollama (local)** — Llama 3.1 8B for extraction. Free, offline, slower.
4. **LiteLLM abstraction** — wrap any provider, switch at config time. Recommended.

**Decision criteria:** cost, latency, quality of structured extraction, offline capability (for Iran), provider diversity (no single-vendor lock-in).

### D2: Database Schema Design
**Effort:** 1-2 days
**Deliverable:** `specs/05_V1_Database_Schema.md`

Design the ER diagram for:
- `user_profiles` (from Phase 2's `UserProfile`)
- `opportunities` (from current record schema)
- `supervisors` (from supervisor finder output)
- `matches` ( scored results linking profile → opportunity)
- `applications` (tracking user actions)
- `bookmarks` (saved positions)
- `digest_preferences` (email settings)

Use SQLAlchemy 2.0 declarative style. Target SQLite for MVP.

### D3: Source Health Audit
**Effort:** 0.5 days
**Deliverable:** `SOURCE_HEALTH.md`

Run each enabled source individually (`--source X`) and record:
- Response time
- Records returned
- Any warnings/errors
- Whether Playwright is required
- Last known working date

This gives a baseline for monitoring source drift over time.

---

## Definition of Done

| Item | Done when |
|------|-----------|
| B1 (academictransfer fix) | `--source academictransfer` runs without `AttributeError` |
| B2 (vpn.txt removal) | File deleted from working tree |
| B3 (.gitignore audit) | All secrets/artifacts covered |
| S2 (utils/records extraction) | `--self-test` passes, `tests/test_utils.py` exists and passes |
| S3 (taxonomy extraction) | `--self-test` passes, `tests/test_taxonomy.py` exists and passes |
| S4 (http extraction) | `--self-test` passes, `--source eso` works live |
| D1 (LLM decision) | Decision document written, founder has weighed in |
| D2 (DB schema) | ER diagram spec written, reviewed |
| D3 (source health) | Audit table completed for all 14 sources |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| S3 (taxonomy extraction) breaks scoring | Run `--self-test` after every function move; compare output against pinned test fixtures |
| S4 (http extraction) breaks proxy chain | Test with `--proxy ""` (direct) and `--proxy socks5h://127.0.0.1:10808` (SOCKS) |
| LLM provider decision delayed | Start with OpenAI as default, abstract behind interface so switch is trivial |
| Source drift during migration | D3 audit gives baseline; pin source test fixtures before extraction |
