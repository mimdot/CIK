# MIGRATION_PLAN.md

Phase 1 plan: reorganize the 7,368-line monolith `phd_aggregator/phd_aggregator.py`
into maintainable modules **without changing behavior**. This is a design
proposal — per the operating rules and `prompts/01`, no code is written until
the founder approves.

## 0. Guiding constraints (non-negotiable)

From `docs/06_Operating_Rules.md`, `docs/05_Repo_Structure.md`, `prompts/01`,
`prompts/08`, and `CONTRIBUTING.md`:

1. **Preserve every feature and behavior.** Identical behavior, identical CLI.
2. **No optimization, no algorithm redesign.** Pure reorganization.
3. **Gradual migration, not one big jump.** The monolith is split module by
   module; each step stays runnable and green.
4. **Release rule:** never start the next phase until the previous one is
   testable and stable.
5. **Self-test must pass:** `python phd_aggregator.py --self-test` before and
   after every step; `test_supervisors.py` stays functional.
6. One self-contained function per source, one YAML per field — the extension
   contract is preserved.
7. Ranking stays deterministic. LLM stays out of scoring.
8. No new features, no removals, no behavior-affecting refactors during Phase 1.

## 1. Target structure

A small package next to the existing file, built module-by-module. The single
file stays as the **entry point + CLI + self-test host** until the final step.

```
phd_aggregator/
├── phd_aggregator.py          # entry point (CLI + main + self-test) — shrinks per step
├── config.yaml
├── fields/*.yaml              # unchanged
├── applicant.yaml / .env      # unchanged, gitignored
├── core/
│   ├── __init__.py
│   ├── config.py              # Config dataclass, constants, build_config, YAML plumbing
│   ├── taxonomy.py            # compile_taxonomy, score_relevance, is_relevant,
│   │                          #   classify_position_type, canonical_country,
│   │                          #   guess_country, country_allowed
│   ├── records.py             # make_record, OUTPUT_FIELDS, dedupe_key, _key_text
│   ├── http.py                # Http, RobotsCache, detect_proxy, anti-bot chain
│   └── utils.py               # normalize_url, logging setup, text helpers, _load_dotenv
├── pipeline/
│   ├── __init__.py
│   ├── filter.py              # filter_records
│   ├── dedupe.py              # dedupe_records, _merge_into
│   ├── freshness.py           # apply_freshness, load_state, save_state
│   ├── run.py                 # run(), sort_key, mark_new, write_outputs, print_summary
│   └── parse_page.py          # parse_position_page (JSON-LD → OG → readability)
├── sources/
│   ├── __init__.py            # registry, @register_source, @seed_adapter, SOURCES
│   ├── base.py                # registry/decorator + seed helpers
│   ├── boards_eu.py           # euraxess, academictransfer, academicjobsonline
│   ├── boards_uk.py           # jobs_ac_uk, findaphd, nature_careers
│   ├── boards_astro.py        # aas, eso, esa, jrecin, iau(stub), astrobetter(stub)
│   ├── linkedin.py            # linkedin (guest search, robots override documented)
│   ├── uni_departments.py     # uni_departments + UNIVERSITY_DEPARTMENTS registry
│   ├── seed_urls.py           # seed_urls + seed adapter registry
│   └── stubs.py               # china, korea, new_zealand stubs
├── toolkit/
│   ├── __init__.py
│   ├── emails.py              # build_email, write_emails, APPLICANT_PROFILE
│   ├── professors.py          # find_professors
│   ├── scholarships.py        # write_scholarships, SCHOLARSHIPS
│   └── dashboard.py           # _HTML_TEMPLATE (results + supervisors dashboards)
└── supervisors/
    ├── __init__.py
    ├── chain.py               # _supervisor_chain, _supervisor_focus, find_supervisors
    ├── aggregate.py           # aggregate_supervisors, _merge variants
    ├── ads.py                 # ads_supervisor_docs
    ├── openalex.py            # openalex_supervisor_docs, openalex_supervisor_authors
    └── arxiv.py               # arxiv_supervisor_docs
tests/
└── test_*.py                  # per-module tests (see §4)
```

This mirrors the target repo layout in `docs/05` (crawler/parser/deduplicator/
profile/matching/ranking/… become `core/`/`pipeline/`/`sources/`/`toolkit/`/
`supervisors/`) while keeping the phase 1 scope strictly structural.

## 2. Migration steps (each independently green)

Every step: extract code verbatim → import it into the monolith → run
`--self-test` → run one live `--limit-per-source` sanity run → commit.
The monolith imports the new module and delegates, so behavior is identical and
the change is verifiable by diffing outputs (same JSON) before/after.

| Step | What moves | Risk | Gate |
|---|---|---|---|
| 1 ✅ | `core/config.py`: Config, CONFIG constants, YAML plumbing, build_config | low | `--self-test`, `--list-fields`, `--list-sources` |
| 2 | `core/utils.py` + `core/records.py`: text helpers, normalize_url, make_record, OUTPUT_FIELDS | low | `--self-test` |
| 3 | `core/taxonomy.py`: taxonomy + scoring + type/geo classification | **medium** (scoring correctness) | `--self-test` (pins taxonomy) |
| 4 | `core/http.py`: Http + robots + proxy detect | **medium** (network paths) | `--self-test` + one `--source euraxess` live run |
| 5 | `sources/`: move each source verbatim in batches, keep registry in monolith until all move | low per source | per-source live run |
| 6 | `pipeline/parse_page.py` + `pipeline/filter.py` | **medium** (seed + gate logic) | `--self-test` (JSON-LD fixture + filter cases) |
| 7 | `pipeline/dedupe.py` + `pipeline/freshness.py` | medium | `--self-test` (dedupe + freshness cases) |
| 8 | `pipeline/run.py`: run(), mark_new, write_outputs, print_summary | medium | `--self-test` pass 1/2 + NEW detection |
| 9 | `supervisors/`: chain, aggregate, ads/openalex/arxiv | medium (live APIs) | `test_supervisors.py --whole-only` |
| 10 | `toolkit/`: emails, professors, scholarships, dashboard template | low | `--no-fetch --extras` against a saved JSON |
| 11 | Shrink `phd_aggregator.py` to: parse_args, main, self_test host, thin re-exports | low | full `--self-test` + full live run |
| 12 | Add `tests/` per module (from the self-test cases) | n/a | `pytest` green |

**Step 1 — DONE (2026-08-02).** `core/config.py` extracted; the monolith
re-imports everything (`from core.config import *` plus explicit underscore
helpers). Three deliberate relocation decisions vs. the table above:

- `_compile_term`/`compile_taxonomy` and the country/ISO2 alias tables
  (`COUNTRY_ALIASES`, `_ALIAS_LOOKUP`, `ISO2_COUNTRY`, `_CANON_TO_ISO2`) moved
  with the config code, because `build_config` calls `compile_taxonomy` and
  `apply_config_yaml` rebuilds `_ALIAS_LOOKUP`. Step 3 re-homes them to
  `core/taxonomy.py`.
- `_script_dir()` now returns the PARENT of `core/`, so config.yaml /
  fields/*.yaml / .env resolution is unchanged.
- The monolith reads `core.config._ALIAS_LOOKUP` (module-qualified) in
  `canonical_country`/`guess_country`, because `_rebuild_alias_lookup()`
  reassigns that name at runtime (a plain `from ... import` would go stale).

Gates passed: `--self-test` (ALL PASSED), `--list-fields`, `--list-sources`,
`--help`, and `pytest tests/test_config.py` (21 passed). A live
`--limit-per-source` sanity run was NOT performed (requires network) — run one
before considering the step fully closed.

## 3. What must NOT change (regression guards)

- **CLI surface**: every flag in `parse_args` keeps its exact name/behavior
  (the self-test and README depend on them).
- **Output artifacts**: `phd_positions.{csv,json,html}` schema (16 `OUTPUT_FIELDS`
  columns), `supervisors_<field>_<country>.*`, `emails/`, `professors.*`,
  `scholarships.*`, `.seen_positions.json` state format.
- **Log lines** the tests/README reference (e.g. per-filter drop counters,
  freshness breakdown, `source X -> N raw records`).
- **Extension contract**: `@register_source(name)` functions still receive
  `(cfg, http)` and return raw records; `@seed_adapter(domain)` still returns
  `{"listings": [...], "link_re": ...}`; `fields/*.yaml` untouched.
- **Config layering** order: CONFIG block → config.yaml → fields/*.yaml → CLI.
- **Politeness**: robots, throttle, retry/backoff, no CAPTCHA solving.
- **Dependency philosophy**: hard deps fail fast; optional deps degrade with a
  clear log line.

## 4. Testing strategy

- Keep the monolith's `--self-test` as the system-level gate (it already pins
  the astronomy taxonomy and uses a separate state path, so it is hermetic).
- Add unit tests per module, extracted from existing self-test cases:
  - `test_taxonomy.py`: score_relevance/is_relevant (title anchor override,
    context-only rejection, require_title_anchor), classify_position_type
    (postdoc-with-PhD-wording), canonical_country.
  - `test_dedupe.py`: URL pass + title/institution pass + merge-winner rules.
  - `test_freshness.py`: deadline/posted/first_seen/undated aging + state file.
  - `test_parse_page.py`: JSON-LD JobPosting fixture, @graph unwrap, OG fallback.
  - `test_emails.py`: subject/body/signature from a record.
  - `test_supervisors.py`: stays as the network sweep (unchanged).
- Use `pytest` (new dev dependency only); the monolith itself needs no
  additional runtime deps.

## 5. Risk analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Import-cycle / circular deps when splitting | high | Strict dependency direction: `core` ← `pipeline` ← `sources`; `core` imports nothing internal. Move bottom-up (steps 1–4 first). |
| Silent scoring drift during taxonomy extraction | high | `--self-test` pins exact taxonomy + scoring; additionally diff full output JSON on a fixed fixture run before/after each step. |
| Source breakage during re-home (endpoint drift is real) | medium | Per-source isolation already logs-and-skips; verify each source with a live `--source X --limit-per-source` run in its move step. |
| CLI/flag or log-text regression | medium | README modes table + self-test assert specific flags/log lines; add a golden CLI smoke test. |
| HTML dashboard template regressions | low | `--self-test` already asserts `html_path` written and > 5 KB; keep template byte-identical when moving. |
| Playwright/proxy paths change behavior | medium | Move `Http` verbatim; gate with a live proxy-enabled run. |
| Slipping into optimization (forbidden) | medium | Review rule: any "improvement" that isn't pure relocation is parked in QUICK_WINS / backlog, not done in Phase 1. |

## 6. What is explicitly OUT of scope for Phase 1

- Profile engine (Phase 2), DB schema (Phase 3), matching engine (Phase 4),
  email digest service (Phase 5), FastAPI layer (Phase 6).
- Any new crawler, new scoring dimension, LLM integration, or non-relocating
  refactor. These belong to later phases or QUICK_WINS/backlog.

## 7. Suggested commit sequence (all gated by `--self-test`)

1. `core/config.py` + tests
2. `core/utils.py`, `core/records.py` + tests
3. `core/taxonomy.py` + tests
4. `core/http.py` + tests
5. `sources/*` (batch per region) + per-source smoke
6. `pipeline/parse_page.py`, `pipeline/filter.py` + tests
7. `pipeline/dedupe.py`, `pipeline/freshness.py` + tests
8. `pipeline/run.py` + tests
9. `supervisors/*` + network sweep
10. `toolkit/*` + tests
11. slim `phd_aggregator.py` entry point
12. `tests/` suite green; full live run + JSON diff vs pre-migration baseline
