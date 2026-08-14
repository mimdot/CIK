# ISSUES.md — Phase 0 audit (2026-08-14 brief)

Built from the working tree on branch `chore/audit-repair`. **Baseline measured,
not assumed:** offline `--self-test` **PASSES**, `pytest tests/` = **726 passed
/ 1 skipped in 88s**. The app works; this is targeted repair, not a rebuild.

Companion: `ARCHITECTURE.md` §6 holds the full astronomy-hardcoding inventory
with file:line evidence. This file is the *work list*.

---

## A. Answers to the three questions you asked up front

### A1. "Is the repo really 8GB?" — **Yes, but none of it is in git.**

| Path | Size | Tracked? |
|---|---|---|
| `dashboard/src-tauri/` (Rust `target/`) | **5.9 G** | no (gitignored) |
| `dashboard/node_modules/` | 789 M | no |
| `phd_aggregator/build/` (PyInstaller) | 413 M | no |
| `phd_aggregator/dist/` (sidecar binary) | 330 M | no |
| `.opencode/` | 63 M | no |
| `.codegraph/` | 17 M | no |
| `phd_aggregator.zip` | 12 M | no (`*.zip`) |
| `phd_aggregator/.http_cache.sqlite` | 9.8 M | no |
| **`.git/` — entire history** | **3.72 MiB** | — |

**Conclusion: there is nothing to rewrite.** Git history is 3.7 MB. The 8 GB is
100 % local build output that a `rm -rf` recreates on demand. No
`git filter-repo`, no BFG, no fresh repo, no destructive operation of any kind.
A fresh `git clone` of this project downloads **under 4 MB**.

Verified with `git check-ignore`: every entry above is already ignored
(`.codegraph/` self-ignores via its own `.gitignore`). **The `.gitignore`
needs no changes** — `git add -A` today stages nothing but your two stray
notes. My earlier suspicion that `phd_aggregator.zip` was exposed was wrong;
`*.zip` covers it. 350 files tracked, largest is a 492 K lockfile.

### A2. "Why did CI fail?" — **Two unrelated, small, real causes.**

- **Backend job** — `python3 -m pytest` → `No module named pytest`.
  `requirements.txt` is the *runtime* manifest and correctly has no test deps;
  the workflow never installs any. Fix: install test deps in CI (a
  `requirements-dev.txt`). *Not* a test weakening — the tests never ran at all.
- **Dashboard job** — `npm run lint` fails on
  `app/(app)/supervisors/page.tsx:150`:
  `react-hooks/preserve-manual-memoization` — "Existing memoization could not be
  preserved". Real cause: the `useMemo` calls `list.sort()`, and React Compiler
  refuses to preserve a memo whose body mutates a value derived from a
  dependency. Fix: sort a copy. **This is a correct rule flagging a real
  latent bug** (in-place sort of a derived array) — I will fix the code, not
  the rule. The second annotation is a `_b` unused-var *warning* in
  `__tests__/supervisors.test.tsx` (does not fail the build; I'll clean it).
- **Release job** was `skipped` only because it `needs: [backend, frontend]`.
  Nothing wrong with it.

### A3. "Where does the engine assume astronomy?" — **12 places; 6 are blockers.**

Full table with file:line in `ARCHITECTURE.md` §6. The one-sentence version:

> `fetch_sources()` picks what to crawl from **one global `sources_enabled` dict**
> in `config.yaml`, and `apply_field_profile()` never touches it. Four sources
> (EURAXESS, FindAPhD, AcademicJobsOnline, LinkedIn) additionally have astronomy
> URLs/facets/keywords hardcoded *inside* them. So a chemistry search crawls the
> AAS Job Register and asks FindAPhD for `/phds/astrophysics/`.

---

## B. Where the brief and the code disagree (flagging, per your rules)

Four items in the brief are already done. I will **verify** each rather than
rebuild it, and spend the time on the genuine gaps instead.

| Brief says | Reality | What I'll actually do |
|---|---|---|
| 1C "NASA ADS is the default backend for all fields" | Per-profile routing exists: `supervisor_source` + `supervisor_ads_db` are set in all 11 profiles (astronomy→ads, biology/chem/CS/econ/math/geology→openalex, physics/cond-mat→ads-physics). OpenAlex is already the general backbone with a country-verified author path. | Fix the **default** (`SUPERVISOR_ADS_DB = "astronomy"`, `core/config.py:439`): a *new* profile that omits the key silently routes to ADS. Add PubMed/Europe PMC (absent) + DBLP (absent) + Crossref. Keep the rest. |
| 3A "PDF support needs a parser… never tell the user to pip install" | `pdfplumber>=0.11` and `python-docx>=1.1` **are already in `requirements.txt`**. Your venv has pdfplumber; the *system* python running your API does not. | The dependency isn't the bug — the **environment split** is. Fix = make the backend fail loudly at startup about its own interpreter, plus a real degrade path. Confirms your report without a re-install. |
| 6A "crawling must move off the UI thread" | It already is — every surface is HTTP→backend, crawl runs in a worker/daemon thread. | Nothing to move. The frozen *feel* is missing per-source streaming + no Cancel. Build those. |
| 2A "Cancel with cancellation tokens" | `cancel_job()` exists but only cancels jobs that have **not started** (`core/tasks.py:505`). | Real work: cooperative cancellation checked between sources + partial-result retention. |

One genuine conflict to call out: **`config.yaml` currently ships
`field_profile: computer_science`**, not astronomy. So the run you saw reporting
`63 records (astronomy)` means the UI passed `field=astronomy` explicitly. Good
news — the field→run wiring works; the sources it then crawls are the problem.

---

## C. Defect list (severity × effort), mapped to your phases

### Phase 1 — field-agnostic engine (highest priority)

| # | Sev | Effort | Issue | Evidence |
|---|---|---|---|---|
| **F1** | **Blocker** | M | Sources are not field-scoped. One global `sources_enabled`; profiles cannot declare their own sources. | `config.yaml:52-66`; `pipeline/run.py:448-457`; `core/config.py:720` |
| **F2** | **Blocker** | M | 4 sources hardcode astronomy internally (EURAXESS facets, FindAPhD listing URLs, AJO category URLs, LinkedIn keywords). | `ARCHITECTURE.md` §6.1 |
| **F3** | High | M | No per-field source *registry*: sources don't declare which fields they serve, so there's no resolver and no "no dedicated sources for X" message. | `sources/base.py:26` |
| **F4** | High | L | Missing field profiles: medicine/health, psychology, social sciences, humanities, environmental science. | `fields/` |
| **F5** | Med | L | Coverage asymmetry: astronomy has 150 departments / 135 anchors vs ~20 / ~80 elsewhere. | §6.3 |
| **F6** | High | S | New/incomplete profiles silently route supervisors to NASA ADS. | `core/config.py:439` + `supervisors/chain.py:297` |
| **F7** | High | S | **Caches are not keyed by field.** `opportunity_list_key()` is global with a 1 h TTL, so switching field can serve the previous field's list — exactly "astronomy results for a chemistry search". | `core/cache.py:179-187` |
| **F8** | Med | M | Subfield multi-select does not exist in the UI; `cfg.subfield` is single-valued and CLI-only. | `supervisors/chain.py:55` |

### Phase 2 — search behavior & control

| # | Sev | Effort | Issue | Evidence |
|---|---|---|---|---|
| **S1** | High | M | Cancel only works before a job starts; no cooperative cancellation, no partial-result retention. | `core/tasks.py:505-522` |
| **S2** | High | S–M | The slow source is **`uni_departments`** — it sweeps the profile's department list (150 URLs for astronomy) at `request_delay: 2.0` s each. Must be opt-in + a manual browse alternative. Runtime to be measured, not guessed. | `sources/uni_departments.py`; `config.yaml:44` |
| **S3** | Med | M | PhD and postdoc are blended: `wanted_position_types: [phd, postdoc]` filters one list. Types are hardcoded regex branches, not data. | `core/taxonomy.py:93-119`; `config.yaml:13` |
| **S4** | Med | M | No country/university normalization on input; scraped country normalization exists (`canonical_country`) but is a hand-written alias map, not ISO-3166/ROR. | `core/utils.py`, `core/config.py` aliases |
| **S5** | **High** | S–M | **Count mismatch (18 vs 63).** Two independent numbers: `records` = `len(deduped)` returned by the pipeline; `total` = row count of the `opportunities` table. Between them sit (a) a **silently swallowed** DB-seed failure and (b) a 1 h cached list. Either desynchronises them. To be **reproduced** before fixing. | `core/tasks.py:139-151`; `api/routes/opportunities.py:40-55` |

### Phase 3 — profile / CV

| # | Sev | Effort | Issue |
|---|---|---|---|
| **C1** | High | S | Parser deps are declared but not present in the interpreter that serves the API → "PDF support needs a parser". Needs startup self-check + honest degrade, and bundling in the desktop sidecar spec. |
| **C2** | High | M | "Could not extract profile from text" is all-or-nothing with a generic message. Must extract partially, say *why*, and stay editable. |
| **C3** | **High** | L | **Keyword picker does not exist.** This is the biggest missing feature in the brief and the one that removes the AI-token dependency. Field → subfields → searchable checkbox list, collapsed by default, chips, free-text add. Data comes from the profiles (already structured as `subfields[].keywords`). |

### Phase 4 — supervisor quality

| # | Sev | Effort | Issue | Evidence |
|---|---|---|---|---|
| **V1** | Med | S | Result cap: CLI prints top 15; API/UI cap to verify. Needs a user setting (default ~100) + pagination + "found vs shown". Must check upstream page sizes too (`SUPERVISOR_AUTHOR_PER_PAGE = 50`). | `supervisors/chain.py:414,452`; `core/config.py:458` |
| **V2** | High | M | Off-field supervisors. Partly F1/F6; then needs anchor-match on recent topics, recency > lifetime weighting, senior-author weighting, country filter via normalized data. | `supervisors/aggregate.py` |
| **V3** | Med | S | Export path must be verified to share the filtered dataset. UI already exports `filtered` client-side (`supervisors/page.tsx:138`) — the suspicion is the *server* rows are unfiltered. Verify, don't assume. |
| **V4** | High | M | `fit_score` is unusable: undefined scale, no explanation, clusters. Needs definition, 0–100 normalization, drill-down, calibration across 3 fields. |

### Phase 5–7 — settings, presentation, repo health

| # | Sev | Effort | Issue | Evidence |
|---|---|---|---|---|
| **U1** | Med | S | Settings leaks CLI internals: "Pass this to the pipeline runner with `--field`". Also a *second* competing field control vs the Opportunities selector. | `settings/page.tsx:122-151` |
| **U2** | Low | S | Weekly digest looks broken; must read "coming soon". | `settings/page.tsx:166` |
| **U3** | Med | S | API-keys + admin pages are shown to normal users. **Both are backed by real, working code** (`/api/v1/apikeys` full CRUD + rotation + usage; `/api/admin/*` metrics, source-health, anomalies, dead-letters). Nothing vestigial found so far — the issue is *visibility*, not deadness. Full report before anything is removed. | `api/routes/apikeys.py`, `admin.py`, `lib/api.ts:419-511` |
| **U4** | Med | M | No live search feedback in the UI beyond "N / total sources"; no elapsed time, no streaming results, no running found-count. | `useRunJob.ts` |
| **U5** | Low | S | No testimonials placeholder, no donation placeholder, no GitHub/email footer links. | — |
| **R1** | Med | S | `phd_aggregator.zip` (12 MB) untracked **and** un-ignored. | `.gitignore` |
| **R2** | High | S | CI backend: pytest never installed. | §A2 |
| **R3** | High | S | CI dashboard: React Compiler memoization error (real latent bug: in-place sort). | §A2 |

### Cross-cutting

| # | Sev | Issue |
|---|---|---|
| **X1** | Med | 27 `except Exception: pass` sites. Only the ones that hide user-visible failure get changed — headed by `core/tasks.py:145` (DB seed) and `core/tasks.py:114` (rq meta save). No mass edit. |
| **X2** | Low | Copy in landing/about/placeholders still says "physics, astronomy". |

---

## D. Proposed order of work

Ordered by *unblocks-the-most* first, and by your rule that a refactor and a
behavior change never share a commit. Every step keeps 726 tests + self-test
green and ends in its own reviewable commit.

**Step 1 — CI green + repo hygiene (R1–R3).** Fast, unblocks every later PR,
zero behavior change. Reproduce both failures, fix pytest install, fix the
in-place sort, ignore the zip. *No history rewrite — see §A1.*

**Step 2 — Field registry: sources become data (F1, F3).** Add a `sources:`
block to the profile schema + a `fields=` declaration on `@register_source`, a
resolver (field sources ∪ general boards, with the "no dedicated sources for X"
log), and profile-scoped `sources_enabled`. Pure plumbing + tests; astronomy's
resolved set must stay byte-identical to today's.

**Step 3 — De-astronomise the four hardcoded sources (F2).** EURAXESS facets,
FindAPhD listing URLs, AJO categories, LinkedIn keywords all become
profile-driven, with astronomy's values moved into `astronomy.yaml` so its
behavior is unchanged. Separate commit per source.

**Step 4 — Cache keying + the count mismatch (F7, S5).** Reproduce 18-vs-63
live, then key caches by field/profile and replace the two competing numbers
with one funnel: `63 found → 41 after field filter → 22 after dedup → 18 open`.

**Step 5 — Field coverage (F4, F5, F6).** New profiles (medicine, psychology,
social sciences, humanities, environmental science) + supervisor-routing
defaults + PubMed/Europe PMC/DBLP/Crossref backends. Each profile verified
against live sources before wiring (per your instruction).

**Step 6 — UI: field + subfield selection (F8, 1B) and Cancel (S1).** The two
controls that make the whole thing usable.

**Step 7 — Keyword picker (C3) + CV robustness (C1, C2).** The picker is
independent of steps 2–6 and is the highest-value UX item; it lands as its own
feature.

**Step 8 — Position types PhD/Postdoc (S3) + slow-source opt-in (S2, measured)
+ name normalization (S4).**

**Step 9 — Supervisor quality (V1–V4)**, ending with the explainable fit score.

**Step 10 — Settings/admin copy + presentation (U1–U5)**, then the full test,
timing, and live-launch pass (Phase 8), README/CONTRIBUTING with the worked
"add a new field + its sources" example.

### Decisions (confirmed 2026-08-14)

1. **Slow source (S2):** confirmed — `uni_departments`. Measure it, make it
   opt-in (OFF by default) with a time-cost warning, and ship the manual
   department/institution browse alternative.
2. **API keys / admin (U3):** **hide from normal users, keep all the code.**
   Nothing is deleted; the pages go behind an admin/role gate.
3. **Live source verification:** **proxy is up — verify live.** Probe every
   candidate source through SOCKS `127.0.0.1:10808` and wire only what
   responds. Polite rate limiting, robots respected, no CAPTCHA work.

---

## E. Progress log

| Step | Status | Commit | Notes |
|---|---|---|---|
| Phase 0 audit (this file + `ARCHITECTURE.md` §5-6) | **done** | `87aaa00` | Baseline: self-test PASS, pytest 726/1 skipped, 88 s. |
| **Step 1 — CI green (R2, R3)** | **done** | `b93c91c`, `13b7d69` | Backend: added `requirements-dev.txt` (pytest was never installed, so the suite never ran). Dashboard: the memoization error was a real in-place `sort()` + a hoisted consumer declared above its `useMemo`; fixed the code, not the rule. Also bumped nanoid (GHSA-2v37-7h3g-55p8, disclosed between runs). **All CI jobs green.** |
| Step 1b — repo hygiene (R1) | **done (no action needed)** | — | `git check-ignore` says everything is already ignored; `.gitignore` needed no change. See §A1. |
| **Step 2 — field registry (F1, F3)** | **done** | `24ace65` (refactor), `6a5a1cb` (behavior) | `SourceInfo`/`SOURCE_INFO`, `register_source(fields=...)`, `resolve_sources_for_field`, `sources:` in profiles. astronomy → the same 13 boards; chemistry → 10, `aas`/`esa`/`eso` skipped. +24 tests. |
| **Step 3 — de-astronomise 4 sources (F2)** | **done** | `c80e02f` | EURAXESS facets, AJO categories, FindAPhD slugs, LinkedIn keywords all profile-driven via `source_options:`. EURAXESS + AJO values **verified live through the proxy**; FindAPhD Cloudflare-blocked from this exit IP and flagged unverified. Astronomy's queries bit-identical. +34 tests. |
| **Step 4 — count mismatch + cache keying (S5, F7)** | **done** | `de540cb` | Four causes found and fixed: no explanation of the shrink; stored rows never stamped with their field; a single global cache key; a silently swallowed save failure. UI now shows `63 found → 41 after field filter → 22 after dedupe → 18 stored` with drop reasons. +12 tests. |

| **Step 5 — field + subfield UI, supervisor routing (F6, F8, 1B, 1C)** | **done** | `d170bdf` | New `/api/fields` + `/api/fields/{name}` catalogue; `FieldPicker` replaces the small dropdown (collapsed subfields, chips, select-all); subfields BOOST rather than gate positions; ADS no longer the accidental default for unindexed fields (`supervisor_ads_db_explicit`). +25 tests. |
| **Step 6 — Cancel (S1)** | **done** | `78561ce` | `core/cancel.py`: cooperative token (threading.Event in-process, Redis key for rq). Measured: cancelled after 3 of 6 sources, **all partial records kept**, 0.46s vs 0.90s. Cancel button + elapsed timer + per-source "skipped". +19 tests. |
| **Step 7 — slow source opt-in (S2)** | **done** | `f15f0bc` | Measured `uni_departments`: **150 pages ≈ 5 min of delays alone** for astronomy, ~20 pages elsewhere. Now OFF by default with the cost stated up front, `--include-slow-sources` / `include_slow`, plus `GET /api/fields/{name}/departments` + a browser UI so you can open departments yourself instantly. +10 tests. |

Running totals: **pytest 838 passed / 1 skipped** (was 726), **jest 109 passed
/ 15 suites** (was 97), eslint + tsc clean, `next build` OK, `--self-test`
green, **all CI jobs green**.
</content>
</invoke>
