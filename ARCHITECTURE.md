# ARCHITECTURE.md

> Fresh map built from the current working tree (2026-08-13). Verified against
> code, a green test suite (696 pytest passed, offline `--self-test` passed),
> and the running entry points. Supersedes the old codebase map, which still
> described the pre-refactor 7,368-line monolith and is now stale.

## 0. Reconciliation with the standing brief (read this first)

The brief describes *"a large Python core (`astra.py`, ~25,000 lines,
largely AI-generated in bulk)"* plus a desktop app and a local live version, and
asks (Phase 3) to *split the monolith into a package*.

**That split has already happened.** On disk today:

- `astra/astra.py` is **528 lines** — a thin CLI shim that
  re-exports a real package (`api/ core/ db/ cli/ sources/ supervisors/
  matching/ pipeline/ fields/ toolkit/`), ~27.8k LOC total across many files.
- The desktop app is **Tauri** (Rust shell + PyInstaller FastAPI sidecar).
- The "live/web version" is a **Next.js 16 dashboard + FastAPI** backend.
- There are **696 passing tests**, a CI workflow, Docker/Caddy prod hardening,
  GDPR endpoints, and beta-ops docs.

So this is a **mature, tested beta product**, not a suspect bulk-dump. The audit
below is written for *that* reality. Where the brief's Phase 1/2 items are
already implemented, the audit says so and narrows the work to the genuine
gaps (per your instruction to flag conflicts rather than rebuild).

---

## 1. The three surfaces & how each starts

| Surface | Start command | Frontend | Backend | Talks via |
|---|---|---|---|---|
| **CLI** | `python astra.py …` | terminal + self-contained `astra_positions.html` | direct in-process import of the package | function calls |
| **Live / web** | `uvicorn api.app:app` + `npm run dev` (dashboard) | Next.js dev/prod server | FastAPI (`api.app:app`) + SQLite/Postgres + optional Redis | **HTTP** (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`) |
| **Desktop** | `./run.sh` (repo root) / bundled app | static Next export (`dashboard/out/`) in a Tauri webview | PyInstaller `astra-api` sidecar (`api/run.py`) on `127.0.0.1:8000` | **HTTP** to localhost |

### CLI
`astra.py` → `main()` → `build_config()` (3-layer: built-in defaults →
`config.yaml` → `fields/<profile>.yaml` → CLI flags) → dispatch to `self_test`,
`find_supervisors`, DB helpers, or `pipeline.run.run()`. The CLI imports the
package directly; there is no server.

### Live / web
- **Backend:** `api/app.py` builds the FastAPI app (CORS, CSRF double-submit,
  security headers, request-id + metrics + anomaly middleware, Sentry, a
  weekly-digest scheduler, `/api/v1` public developer API with scoped Bearer
  keys). `api/run.py` runs it under uvicorn.
- **Frontend:** `dashboard/` (Next 16.3 / React 19.2, App Router, Tailwind v4,
  shadcn). `lib/api.ts` wraps every endpoint; auth is an httpOnly `cik_token`
  cookie + `csrf_token` double-submit; API-key clients use `Bearer`.
- **Prod:** `docker-compose.prod.yml` + `Dockerfile` (non-root API image,
  `cap_drop`, `no-new-privileges`) + `caddy/` (TLS). Postgres/Redis/worker per
  the compose files; `core/tasks.py` uses rq when `REDIS_URL` is reachable.

### Desktop (Tauri)
`dashboard/src-tauri/src/lib.rs` `spawn_sidecar()` launches the bundled
`astra-api` binary on `127.0.0.1:8000` with a per-launch random `ASTRA_SECRET_KEY`,
`DATABASE_URL=sqlite://<app-data>/astra.db`, invites off, insecure cookies
(local HTTP), scheduler off; it streams sidecar logs to `<app-data>/api.log` and
kills the child on exit. `lib/api.ts` `apiBase()` uses the base the shell
injects as `window.__ASTRA_API_BASE__`, falling back to the web default.
`tauri.conf.json` serves the static
export from `../out` and declares `sidecar/api/astra-api` as `externalBin`.
`./run.sh` at the repo root builds the sidecar and the app (only when stale)
and launches. It builds through the **Tauri CLI**, never plain `cargo build`:
the latter yields a binary that opens a window and renders nothing, because
the frontend is not embedded in it.

**Frontend↔backend is HTTP over localhost on every surface** — no IPC, no
subprocess-per-request, no direct Python import from the UI.

### Who serves the supervisor endpoint, and who starts it

Both searches are plain HTTP to the same FastAPI process; neither runs
in-process in the UI. What differs is the **gate in front of each**, and that
difference is the whole reason one worked while the other reported "Cannot
reach the API server":

| | Position search | Supervisor search |
|---|---|---|
| Endpoint | `POST /api/pipeline/run` | `POST /api/supervisors/run` |
| Auth | **none** | `Depends(get_current_user)` |
| Page | `/opportunities` — **not** wrapped in `AuthGate` | `/supervisors` — wrapped in `AuthGate` |
| Worker | `core.tasks.run_pipeline_job` | `core.tasks.enqueue_supervisor_job` → `cli.commands.sync_supervisors_cmd` |
| Concurrency | 3 slots | **1** (`_supervisor_slots`); a second run is refused with 429 |

`AuthGate` calls `GET /api/auth/me` on mount. A *network-level* failure there
(status 0) renders "Cannot reach the API server. Is it running?" **in place of
the entire page**, so the supervisor feature disappears whenever the backend is
not reachable at that instant — while `/opportunities`, having no gate and no
auth, keeps working from cached rows and looks healthy.

#### Desktop lifecycle (`dashboard/src-tauri/src/lib.rs`)

1. `setup()` spawns `boot_and_watch` on a background thread so the window paints
   immediately instead of freezing while a PyInstaller onefile unpacks.
2. `sidecar_path()` resolves `astra-api` **next to `current_exe()`** — where Tauri
   puts `externalBin` on every layout. Not `BaseDirectory::Executable`: that is
   `dirs::executable_dir()`, the user's `~/.local/bin`, and using it meant the
   app never found its own backend (and on macOS/Windows, where that directory
   is `None`, could not even resolve a path).
3. `spawn_sidecar()` picks a port — 8000 if free, otherwise an OS-assigned one —
   and starts `astra-api` with the desktop env (`NO_PROXY`/`no_proxy` include
   `localhost,127.0.0.1,::1` so a system-wide SOCKS/HTTP proxy cannot swallow
   loopback traffic).
4. `wait_for_health()` polls `GET /health` over raw TCP until it answers 200
   (90 s budget). **Only then** is a base URL published. Before this existed the
   port was injected immediately and any call made during the unpack window
   failed as "cannot reach the API server".
5. `on_page_load` re-injects `window.__ASTRA_API_BASE__` on **every** page load.
   The previous one-shot `eval()` at setup was thrown away by the first
   navigation, after which the frontend fell back to `:8000` — the wrong port
   whenever the shell had picked another.
6. `lib/api.ts` `apiBase()` honours that global **whenever it is present**. It
   used to require `window.__TAURI__` first, which Tauri v2 defines only under
   `app.withGlobalTauri` (unset here) — so the gate was always false and every
   port the shell picked other than 8000 was unreachable. `AuthGate` also waits
   while `__ASTRA_API_READY__ === false` with no error, instead of racing the
   sidecar's unpack and reporting "cannot reach the API server" on every cold
   start.
7. If the child dies while the app is open, the watcher restarts it.
8. On failure the shell publishes `window.__ASTRA_API_ERROR__` with the reason and
   the tail of `<app-data>/api.log`; `AuthGate` renders that instead of asking
   the user whether the backend they cannot start is running.

#### Schema drift is repaired at startup

`init_db()` runs `create_all()` and then `reconcile_columns()`, which adds any
nullable column the models declare that an existing table lacks. `create_all`
only creates missing *tables*, and the desktop app never runs Alembic — so a
model that gains a column otherwise leaves every older database one column
short. That is not hypothetical: `supervisors.fit_explanation` was missing, and
the supervisor search found 89 German candidates, failed to save all 89 with
`no such column`, and reported "completed, 0 records".

---

## 2. Backend package map (`astra/`)

| Package | Role |
|---|---|
| `astra.py` | CLI shim + `parse_args`/`main`/`new_field_wizard`; re-exports the package for back-compat. |
| `core/` | Cross-cutting: `config` (3-layer loader, field profiles), `http` (proxy/anti-bot `Http`, robots, SSRF guard), `llm` (`LLMRouter`, litellm), `profile_schema`/`profile` (`UserProfile`, `extract_profile`), `taxonomy` (relevance scoring), `records`, `cache` (Redis/in-mem result cache), `tasks` (rq/thread jobs + digest scheduler), `digest`, `email`, `ratelimit`, `anomaly`, `source_monitor`, `observe`, `env`, `utils`. |
| `sources/` | One file per job board (euraxess, nature_careers, jobs_ac_uk, findaphd, academictransfer, academicjobsonline, aas, jrecin, eso, esa, linkedin, uni_departments, seed_urls) + `base.py` (`@register_source`, `SOURCES` registry) + `stubs.py` (iau/astrobetter, disabled). |
| `pipeline/` | `run.py` (the orchestrator: fetch→filter→freshness→dedupe→sort→score→write CSV/JSON/HTML), `filter`, `dedupe`, `freshness`, `parse_page` (JSON-LD/OpenGraph/readability). |
| `matching/` | `scorer.py` — deterministic `score_match(profile, opp, cfg)` → `MatchResult(overall_score, explanation)`. |
| `supervisors/` | `chain.py` (`find_supervisors`, source selection), `ads.py` (NASA ADS), `arxiv.py` (fallback), `openalex.py` (any field, no token), `aggregate.py`. All fetch through the proxy-aware `Http`. |
| `db/` | `models.py` (SQLAlchemy: User, UserProfileRow, Opportunity, Supervisor, Bookmark, DigestPreference, ApiKey…), `repositories.py`, `init.py` (`resolve_db_url`, `seed_from_json`), `alembic/` migrations. |
| `api/` | `app.py` + `routes/` (auth, profile, opportunities, matches, supervisors, bookmarks, preferences, pipeline+jobs, invites, admin, email, apikeys, assistant, account, `v1/`) + `deps`, `schemas`, `serializers`, `security`, `scopes`, `metrics`. |
| `cli/commands.py` | DB-backed CLI ops: `build_profile_cmd`, `seed_db_cmd`, `show_profile_cmd`, `make_admin_cmd`, `sync_supervisors`. |
| `toolkit/` | CLI extras (`--write-emails`, `--find-professors`, `--scholarships`). Not exposed via the API. |
| `fields/` | 11 field profiles (`astronomy`, `physics`, `biology`, `chemistry`, `computer_science`, `economics`, `engineering`, `geology`, `geophysics_hydro`, `condensed_matter`, `mathematics`) + `template.yaml`. |
| `selftest.py` | Offline hermetic pipeline self-test (`--self-test`). |

---

## 3. Data flow — the crawl pipeline (shared by CLI & API)

```
sources.SOURCES (enabled)              ← config.yaml sources_enabled / --source
   → fn(cfg, http)  [CONCURRENT pool]  ← core.http.Http (proxy, robots, retries)
   → make_record
   → filter_records   (type gate → relevance → expiry → region)
   → apply_freshness  (+ .seen_positions.json state, NEW detection)
   → dedupe_records   (url key, then title+institution)
   → sort_key         (relevance → deadline → posted)
   → [profile] apply_profile_matching → match_score + match_explanation
   → write_outputs    (CSV + JSON + self-contained HTML dashboard)
```

The **same** `pipeline.run.run()` is invoked two ways:

1. **CLI:** `main()` → `run(cfg, …)`.
2. **API:** `POST /api/pipeline/run` → `core.tasks.enqueue_pipeline_job()` →
   rq worker *or* in-process daemon thread → `run_pipeline_job()` →
   `pipeline.run.run()` → seed the `opportunities` table from the JSON →
   invalidate caches. Progress is polled via `GET /api/pipeline/status` /
   `GET /api/jobs/{id}` (coarse `running`/`completed`/`failed` + final count).

So the API path runs the crawl **off the request thread** (UI never blocks), and
since the 2026-08-13 pass the crawl itself is concurrent (`ThreadPoolExecutor`,
`ASTRA_SOURCE_CONCURRENCY`, default 6) and streams per-source progress events.

### The source layer is NOT field-aware (the core defect)

`fetch_sources` decides what to crawl from **`cfg.sources_enabled`** — a single
global dict in `config.yaml`, identical for every field. `apply_field_profile()`
(`core/config.py:720`) overlays a profile's taxonomy, weights and supervisor
routing, but **never touches `sources_enabled`**. So selecting *chemistry* still
crawls the AAS Job Register, ESO and ESA, and still asks EURAXESS for its
astronomy facets. See §6 for the full inventory.

### Supervisor finder (independent of the crawl)
`--find-supervisors` (CLI) and `POST /api/supervisors/run` (API →
`enqueue_supervisor_job` → `sync_supervisors`) both drive
`supervisors.chain.find_supervisors`: pick source (`auto`=ADS for astro/physics
else OpenAlex; token-gated) → fetch docs through the proxy `Http` → aggregate by
author with senior-author + in-country weighting → write/ upsert rows. The
dashboard reads ranked rows from `GET /api/supervisors`.

### Matching / digest
`matching.score_match` scores stored opportunities against the active
`UserProfile` deterministically (topic/method/location/…, with an explanation
string). The weekly digest (`core.tasks.send_digest_job` → `core.digest`) reuses
the same scorer and emails the top matches.

---

## 4. Config, field profiles, proxy

- **3-layer config** (`core/config.build_config`): built-in defaults →
  `config.yaml` → `fields/<profile>.yaml` (`--field` / `field_profile:`) → CLI
  flags. `GET /api/fields` exposes the profile list to the dashboard dropdowns.
- **Field profile** = `core_anchors` / `context_terms` / `negative_terms` /
  `search_terms` / `weights` / `threshold` (+ optional `subfields`,
  `departments`, `supervisor_*`). Editable YAML; `--new-field` scaffolds one.
- **Proxy / anti-bot (Iran):** `config.yaml proxy: socks5h://127.0.0.1:10808`
  with auto-detect + direct fallback. `core.http.Http` routes requests,
  curl_cffi, and the Playwright browser through it and enforces robots + polite
  delay; there is an SSRF guard blocking private/loopback fetches. Supervisor
  ADS/arXiv/OpenAlex/ORCID calls all go through this same `Http`.

---

## 5. Dead code, silent failure, and thread safety

- **Dead / unwired (intentional):** `sources/stubs.py` (`iau`, `astrobetter` —
  registered but disabled), `toolkit/` (emails/professors/scholarships, CLI-only,
  no API route), the bulk re-exports in `astra.py` (a test pins them).
- **Duplication:** none material. One module per source; no competing
  fetcher/parser/filter implementations. (The brief's "P0 competing versions"
  does not exist on disk.)
- **Silent excepts:** 140 `except Exception` outside tests, **0 bare `except:`**.
  27 of them end in a bare `pass`. Most are deliberate graceful degradation
  (one bad card must not sink a crawl). The ones that genuinely hide bugs are
  tracked individually — notably the DB-seeding swallow in
  `core/tasks.py:145`, which is the prime suspect for the count mismatch.
- **UI thread:** no crawling happens on it. Every surface talks HTTP to the
  backend; the crawl runs in an rq worker or an in-process daemon thread. The
  dashboard polls `GET /api/jobs/{id}`. The real UX defect is not blocking but
  **absence of cooperative cancellation** — `cancel_job` only cancels jobs that
  have not *started* (`core/tasks.py:505`); a running crawl ignores it.

---

## 6. Where the engine assumes astronomy (full inventory)

Legend: **[BLOCKER]** makes non-astronomy searches wrong · **[TAXONOMY]** is a
default that a field profile already overrides · **[COPY]** user-visible text.

### 6.1 Source layer — the real problem

| Where | What is hardcoded | Effect on a non-astronomy search |
|---|---|---|
| `config.yaml:52-66` `sources_enabled` | One global on/off list; `aas`, `eso`, `esa` always on | **[BLOCKER]** astronomy-only boards are crawled for every field |
| `core/config.py:720` `apply_field_profile` | Never writes `sources_enabled` | **[BLOCKER]** a profile cannot restrict its own sources |
| `sources/euraxess.py:32-39` | `ASTRO = [job_research_field:34/35/37]` facets | **[BLOCKER]** EURAXESS is asked for astronomy offers regardless of field |
| `sources/findaphd.py:28-31` | `LISTING_URLS = /phds/astrophysics/, /phds/astronomy/` | **[BLOCKER]** FindAPhD only ever returns astronomy projects |
| `sources/academicjobsonline.py:21-24` | `CATEGORY_URLS = physics/Astronomy, physics/Astrophysics` | **[BLOCKER]** AJO only ever returns astronomy posts |
| `sources/linkedin.py:24-25` | `LINKEDIN_KEYWORDS = ["PhD astronomy", …]` | **[BLOCKER]** LinkedIn queried with astronomy keywords only |
| `sources/aas.py`, `eso.py` | AAS Job Register RSS, ESO recruitment RSS | astronomy-only orgs; correct *for astronomy*, noise elsewhere |
| `sources/esa.py:36` | `ESA_QUERIES = ["PhD", "science"]` | field-neutral but space-sector only |
| `sources/uni_departments.py:23-331` | `UNIVERSITY_DEPARTMENTS` — 144 astronomy dept URLs | fallback only; profiles with a `departments:` block are respected |
| `sources/stubs.py` | `iau`, `astrobetter` | disabled; astronomy-only by nature |
| `seeds.txt` | hand-picked seed URLs | currently empty of real seeds (21 lines, all comments) |

**Field-driven already** (they query `cfg.search_terms`, so they follow the
profile today): `nature_careers` (6 terms), `jobs_ac_uk` (4), `jrecin` (3),
`academictransfer` (2).

### 6.2 Taxonomy / scoring defaults

| Where | What | Severity |
|---|---|---|
| `core/config.py:102-244` | `CORE_ANCHORS` (135 astro terms), `CONTEXT_TERMS`, `SEARCH_TERMS` built-in defaults | **[TAXONOMY]** — every `fields/*.yaml` replaces them |
| `core/config.py:355` | `FIELD_PROFILE = "astronomy"` default profile | **[TAXONOMY]** — `config.yaml` currently overrides to `computer_science` |
| `core/config.py:439-441` | `SUPERVISOR_ADS_DB = "astronomy"`, `SUPERVISOR_ARXIV_CAT = "astro-ph*"` | **[BLOCKER for new fields]** — a profile that omits `supervisor_ads_db` routes to NASA ADS when a token is set (`supervisors/chain.py:297`) |
| `selftest.py` | Astronomy-only offline fixtures | test-only; needs a non-astro counterpart |

### 6.3 Coverage asymmetry between profiles

Astronomy is far deeper than every other shipped field — this is the "raise the
others" work, not a bug:

| profile | departments | subfields | core anchors |
|---|---|---|---|
| astronomy | **150** | 7 | **135** |
| engineering | 25 | 8 | 169 |
| economics | 24 | 8 | 71 |
| mathematics / geophysics_hydro | 22 | 8 / 4 | 109 / 49 |
| computer_science / physics | 20 | 8 | 68 / 94 |
| biology | 19 | 9 | 119 |
| chemistry / geology | 18 | 8 | 78 / 125 |
| condensed_matter | 15 | 4 | 51 |

**Missing entirely:** medicine/health, psychology, social sciences, humanities,
environmental science.

### 6.4 User-visible copy

| Where | Text |
|---|---|
| `dashboard/app/(public)/landing/page.tsx:29` | "physics, astronomy, and related fields" |
| `dashboard/app/(public)/about/page.tsx:14` | "built and tuned for physics, astronomy…" |
| `dashboard/app/(app)/profile/page.tsx:184`, `onboarding/page.tsx:289` | astronomy CV placeholder |
</content>
</invoke>
