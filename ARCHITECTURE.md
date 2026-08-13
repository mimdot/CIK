# ARCHITECTURE.md

> Fresh map built from the current working tree (2026-08-13). Verified against
> code, a green test suite (696 pytest passed, offline `--self-test` passed),
> and the running entry points. **Supersedes `CODEBASE_MAP.md`**, which still
> describes the pre-refactor 7,368-line monolith and is now stale.

## 0. Reconciliation with the standing brief (read this first)

The brief describes *"a large Python core (`phd_aggregator.py`, ~25,000 lines,
largely AI-generated in bulk)"* plus a desktop app and a local live version, and
asks (Phase 3) to *split the monolith into a package*.

**That split has already happened.** On disk today:

- `phd_aggregator/phd_aggregator.py` is **528 lines** — a thin CLI shim that
  re-exports a real package (`api/ core/ db/ cli/ sources/ supervisors/
  matching/ pipeline/ fields/ toolkit/`), ~27.8k LOC total across many files.
- The desktop app is **Tauri** (Rust shell + PyInstaller FastAPI sidecar).
- The "live/web version" is a **Next.js 16 dashboard + FastAPI** backend.
- There are **696 passing tests**, a CI workflow, Docker/Caddy prod hardening,
  GDPR endpoints, and beta-ops docs.

So this is a **mature, tested beta product**, not a suspect bulk-dump. The audit
below and `ISSUES.md` are written for *that* reality. Where the brief's Phase 1/2
items are already implemented, `ISSUES.md` says so and narrows the work to the
genuine gaps (per your instruction to flag conflicts rather than rebuild).

---

## 1. The three surfaces & how each starts

| Surface | Start command | Frontend | Backend | Talks via |
|---|---|---|---|---|
| **CLI** | `python phd_aggregator.py …` | terminal + self-contained `phd_positions.html` | direct in-process import of the package | function calls |
| **Live / web** | `uvicorn api.app:app` + `npm run dev` (dashboard) | Next.js dev/prod server | FastAPI (`api.app:app`) + SQLite/Postgres + optional Redis | **HTTP** (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`) |
| **Desktop** | `npm run tauri:dev` / bundled app | static Next export (`dashboard/out/`) in a Tauri webview | PyInstaller `cik-api` sidecar (`api/run.py`) on `127.0.0.1:8000` | **HTTP** to localhost |

### CLI
`phd_aggregator.py` → `main()` → `build_config()` (3-layer: built-in defaults →
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
`cik-api` binary on `127.0.0.1:8000` with a per-launch random `CIK_SECRET_KEY`,
`DATABASE_URL=sqlite://<app-data>/phd_data.db`, invites off, insecure cookies
(local HTTP), scheduler off; it streams sidecar logs to `<app-data>/api.log` and
kills the child on exit. `lib/api.ts` detects `window.__TAURI__` and points
`API_BASE` at `http://localhost:8000`. `tauri.conf.json` serves the static
export from `../out` and declares `sidecar/api/cik-api` as `externalBin`.

**Frontend↔backend is HTTP over localhost on every surface** — no IPC, no
subprocess-per-request, no direct Python import from the UI.

---

## 2. Backend package map (`phd_aggregator/`)

| Package | Role |
|---|---|
| `phd_aggregator.py` | CLI shim + `parse_args`/`main`/`new_field_wizard`; re-exports the package for back-compat. |
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
   → fn(cfg, http)  [SEQUENTIAL loop]  ← core.http.Http (proxy, robots, retries)
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

So the API path runs the crawl **off the request thread** (UI never blocks), but
the crawl itself is **sequential across sources** and reports no per-source
progress — see `ISSUES.md` Phase 1.

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
</content>
</invoke>
