# ISSUES.md — Phase 0 audit findings

Built from the current working tree (2026-08-13). Baseline established before any
change: **`--self-test` passes**, **`pytest` = 696 passed in ~85s** (offline,
`CIK_TESTING=1`). This is a working, tested beta — the goal is targeted repair,
not a rebuild.

## A. Reconciliation: brief vs. reality

| Brief item | Reality on disk | Verdict |
|---|---|---|
| **P3** "split the 25k-line monolith into a package" | Already a package; `phd_aggregator.py` is a 528-line shim. | **Done** — nothing to split. Skip/repurpose P3 to docs + gitignore + minor cleanups. |
| **P0** "several competing versions of the same fetcher/parser/filter" | One file per source; no duplicate business logic (only expected dup names in tests/migrations). | **Not present.** |
| **P2C** supervisor search by country "not usable live" | **Fully wired live:** `supervisors/page.tsx` (country + field + "Run online search") → `POST /api/supervisors/run` → `enqueue_supervisor_job` → ADS/OpenAlex/arXiv chain → DB upsert → polled via `useRunJob`. Country is free-text (any country). | **Largely implemented.** Remaining gaps are polish: multi-select country, missing-token UX, per-query caching, CSV/JSON export from UI. |
| **P2B** "CV upload actually does something" | **Paste-text** extraction works: `POST /api/profile/build` → `extract_profile()` → editable profile fields. **No file upload** (no `UploadFile`/multipart anywhere); pdfplumber/PyMuPDF/python-docx not installed nor in `requirements.txt`. | **Partially done.** Real gap = PDF/DOCX/TXT **file** upload + parsing, and surfacing which CV terms matched each position. |
| **P2A** "change field at runtime — impossible" | Field dropdowns exist (onboarding, home, supervisors) fed by `/api/fields`; switching re-filters/re-scores stored matches. **But** `PipelineRunRequest`/`enqueue_pipeline_job` take **no `field`**, and `run_pipeline_job` builds config with `no_config=True` → the crawl always uses the built-in **astronomy** taxonomy regardless of UI selection. | **Half-wired — real bug** (see H1). Field affects post-hoc filtering but not what the crawl collects/scores. |
| **P1** concurrency / incremental cache / streaming | Sources fetched **sequentially**; no ETag/Last-Modified conditional-GET cache; job progress is coarse (`running/completed`). Off-thread already (API). | **Genuine open work.** |

**Bottom line:** most of the brief's "broken" features are built. The high-value
work is a *small* set of real defects + Phase-1 speed, not re-implementation.

## B. Duplication & dead code

- **Duplication:** none material. `phd_aggregator.py`'s bulk re-exports are an
  intentional back-compat shim (a test asserts monolith names stay reachable).
- **Dead / unwired (intentional, low priority):**
  - `sources/stubs.py` (`iau`, `astrobetter`) — registered but disabled by design.
  - `toolkit/` (emails/professors/scholarships) — CLI-only; not exposed via API.
  - `phd_aggregator.py` re-exports many symbols only used for back-compat.
  - `@app.on_event("startup")` — deprecated FastAPI API (still works; warns).

## C. Bugs / risks (prioritized — severity × effort)

| # | Sev | Effort | Issue | Evidence |
|---|---|---|---|---|
| **H1** | High | S–M | **Field profile never reaches the pipeline run.** UI field selection can't change what the crawl collects/scores. | `api/schemas.py:140` (`PipelineRunRequest` has no `field`); `core/tasks.py:69-74` (`no_config=True`, only `country`). |
| **H2** | High | S | **Repo-hygiene landmines for a public release.** `.gitignore` does *not* cover `phd_aggregator.zip` (12M), `phd_aggregator/build/` (413M), `dist/` (330M), `nohup.out`, `*.spec`, `supervisors_ism_germany.*`; they show as untracked (`??`) and would be committed on a stray `git add`. `phd_data.db` + `phd_data.db.bak` **are tracked**. | `git check-ignore` misses them; `git ls-files` shows the DBs. |
| **M1** | Med | M–L | **Phase-1 concurrency:** sources fetched strictly sequentially — one slow/hanging source blocks the rest of the run. | `pipeline/run.py:433-455`. |
| **M2** | Med | M | **No incremental HTTP cache** (ETag/Last-Modified/conditional GET); every run is a full re-crawl. `core/cache.py` caches *result lists* only. | `core/http.py` (no 304 handling). |
| **M3** | Med | M | **No streaming per-source progress.** Job status is coarse; dashboard shows a spinner, not per-source counts/errors. | `core/tasks.py`, `api/routes/pipeline.py`, `hooks/useRunJob.ts`. |
| **M4** | Med | M | **CV file upload missing** (2B): only pasted text; no PDF/DOCX/TXT parse; parsing libs absent. | no `UploadFile`; `requirements.txt` lacks pdfplumber/PyMuPDF/python-docx. |
| **L1** | Low | S | **Desktop sidecar proxy not verified.** Sidecar runs with `current_dir=<app-data>`; `build_config` may not find `config.yaml`, so supervisor/ADS calls from the *packaged* app may not use the SOCKS proxy (Iran). CLI path is fine (proxy-aware `Http`). | `src-tauri/src/lib.rs:90`; `core/config`. |
| **L2** | Low | S | **Tauri sidecar hardcodes port 8000** (no free-port fallback though `api/run.py` supports `CIK_API_PORT`); `API_BASE` hardcoded. Port clash ⇒ silent white screen. | `src-tauri/src/lib.rs:24`; `lib/api.ts:39`. |
| **L3** | Low | S | **`@app.on_event` deprecated** → migrate to lifespan handlers. | `api/app.py:310`. |
| **L4** | Low | S | **Docs thin / proxy undocumented.** root `README.md` is 659 bytes; `.env.example` documents ADS/OpenAlex but not the SOCKS proxy; `CODEBASE_MAP.md` is stale. | file sizes; `.env.example`. |
| **I1** | Info | — | 131 `except Exception` (0 bare `except:`). Mostly intentional graceful-degradation; spot-review the silent ones, don't mass-change. | grep sweep. |
| **I2** | Info | — | `CIK_SECRET_KEY` unset ⇒ insecure dev key (already warns); ensure set in prod. Large uncommitted working tree (41 modified / 21 untracked). | pytest warning; `git status`. |

## D. Proposed order of work (for your confirmation)

Each step is small, independently testable, and keeps the 696 tests + self-test
green. Refactors and behavior changes stay in separate commits (per your rules).

1. **H2 — hygiene first (safe, fast).** Extend `.gitignore` (zip, build/, dist/,
   `*.spec`, `nohup.out`, `src-tauri/target`, ad-hoc `supervisors_*` outputs,
   CV upload dir). Decide on `phd_data.db*`: stop tracking (untrack + ignore) or
   keep as a seed fixture — **your call**.
2. **H1 — wire field into the run (the flagship 2A fix).** Add `field` to
   `PipelineRunRequest` → `enqueue_pipeline_job` → `run_pipeline_job` → build
   config *with* that field; ensure caches are keyed by field so switching
   invalidates stale results. Add a regression test.
3. **P1 speed — measure, then concurrency.** Instrument a real run
   (startup / per-source network / CPU), report numbers, then parallelize the
   source loop with a per-domain cap, per-source timeout + isolation, preserving
   rate-limiting; re-report. (M2/M3 caching + streaming as follow-ups.)
4. **2B — CV file upload.** Add PDF/DOCX/TXT parsing behind an upload endpoint,
   feed the existing `extract_profile`, keep it local-only, gitignore the upload
   dir, surface matched terms per position.
5. **2C polish.** Multi-select country, missing-ADS-token actionable message,
   per-query supervisor cache, CSV/JSON export from the UI.
6. **Docs & minor cleanups (repurposed P3).** README (install / proxy / ADS /
   CLI vs web vs desktop), CONTRIBUTING (add-a-source / add-a-field worked
   examples), lifespan migration (L3), sidecar port/proxy robustness (L1/L2).

**Decisions (confirmed):** proceed in the order above; **untrack + gitignore**
`phd_data.db*`.

## E. Progress log

| Step | Status | Notes |
|---|---|---|
| H2 hygiene | **done** (committed `5814f3b`) | `.gitignore` extended; `phd_data.db*` untracked (files kept). |
| Phase 0 docs | **done** (committed `cfb4f80`) | `ARCHITECTURE.md` + `ISSUES.md`. |
| H1 field→run | **done** (working tree) | `field` threaded schema→route→tasks→`build_config`; "Field to crawl" dropdown; 422 on unknown field. Tests: +3 py, +1 UI. |
| P1 concurrency (M1) | **done** (working tree) | Isolated `Http` per source, `ThreadPoolExecutor`, deterministic order; `CIK_SOURCE_CONCURRENCY` (=1 restores sequential). **Measured 13s→3s (4.3×)**. Tests: +3. |
| 2C supervisor polish | **done** (working tree) | Multi-country (comma-separated → array), CSV/JSON export from the UI, actionable ADS-token hint. Tests: +2. (Per-country re-search already instant via DB + list cache.) |
| Docs | **done** (working tree) | Rewrote root `README.md` (install / proxy / ADS / CLI vs web vs desktop); added root `CONTRIBUTING.md` (worked examples). |
| **2B CV file upload** | **done** (working tree) | `core/cv.py` (TXT/PDF/DOCX, local-only, clear errors) + base64-JSON `POST /api/profile/extract-cv` (no `python-multipart`) + Profile-page upload control feeding the existing extract→edit flow. TXT + endpoint + guards verified here; PDF/DOCX activate on `pip install pdfplumber python-docx`. Tests: +11 py, +1 UI. |
| **P1 M3 streaming progress** | **done** (working tree) | `fetch_sources` emits start + per-source `{status,records,duration}` events → `run_pipeline_job` records them (in-memory job record / rq `job.meta`) → `get_job_status` surfaces `progress` → `useRunJob` + the Engine-run dialog stream "N / total sources" and per-source records/errors. Tests: +2 py, +1 UI. |
| **L3 `on_event`→lifespan** | **done** (working tree) | Migrated the deprecated startup handler to a `lifespan` context manager (removes both deprecation warnings). |
| **P1 M2 conditional-GET cache** | **done** (committed) | `core/http_cache.py` (SQLite, thread-safe, shared across workers) + `Http.get/raw_get` revalidate with If-None-Match/If-Modified-Since → 304 serves the cached body; store 200s with validators. `Config.http_cache`/`force_refresh` + `--force-refresh`/`--no-http-cache`. Off under `CIK_TESTING`; cache file gitignored. Tests: +6. |
| **L1/L2 (sidecar proxy/port)** | **done** (committed) | Tauri shell picks a free port (prefer 8000) + injects `window.__CIK_API_BASE__`; `apiBase()` reads it with a fallback. `CIK_PROXY` env + `_find_config_path` searches the frozen exe dir + shell forwards `CIK_PROXY`. Also fixed a pre-existing Rust compile error (`io::Write`→`fmt::Write`) so the desktop shell builds. **Verified with `cargo check`.** Tests: +5 py, +3 UI. |
| Lazy imports (L-startup) | open (low value) | Only the CLI shim eagerly loads `pandas`/`sqlalchemy`; the desktop **sidecar** (api.app) already doesn't, so the "instant startup" win is small and the shim's back-compat re-export test makes it delicate. The only item left. |

Verification to date: **`pytest` 726 passed / 1 skipped**, **dashboard jest 97
passed / 15 suites**, `cargo check` clean, `tsc` clean, offline `--self-test` green.
</content>
