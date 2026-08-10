# CODEBASE_MAP.md

File-by-file map of the repository. Line numbers refer to current on-disk
files (verified against the working tree).

## Repository root

| Path | What it is |
|---|---|
| `README.md` | Root readme: the "read-first-in-order" entry point pointing to docs, prompts, specs. Says this folder is the working source of truth. |
| `docs/` | 7 design docs (see below). |
| `prompts/` | 8 agent prompts: 6 OpenCode phase prompts + 2 Kimi review/rules prompts. |
| `specs/` | 4 v1 specs: data contracts, matching weights, email digest format, API outline. |
| `phd_aggregator/` | The working prototype (the monolith + config + profiles + docs). |
| `.codegraph/` | CodeGraph index (`codegraph.db`) + its own `.gitignore`. |

## `docs/`

| File | Content (in one line) |
|---|---|
| `00_Project_Index.md` | What the project is; what an agent should do next; the one-sentence goal. |
| `01_Project_Overview.md` | Mission, product promise, first-launch philosophy, what the product is not, design principle (fit quality > result count). |
| `02_PRD_v1.md` | Target users, jobs-to-be-done, functional + non-functional requirements, success metrics. |
| `03_Architecture_v1.md` | Three engines (Knowledge / Identity / Intelligence), data flow, LLM-support-not-define principle, recommended stack, early modules, data model, matching dimensions, launch sequence. |
| `04_Roadmap_and_Milestones.md` | 6 months: Phase 1–6 (refactor → profile → DB → matching → email → API), then dashboard/tracking/beta/launch/expansion. Release rule: don't start next phase until previous is stable. |
| `05_Repo_Structure.md` | Proposed target layout (backend/ frontend/ prompts/ docs/ specs/ tests/ scripts/) + the gradual-migration rule. |
| `06_Operating_Rules.md` | Agent rules: preserve behavior, deterministic ranking, LLM only where it adds value, testable tasks, stop-and-ask on ambiguity. |

## `prompts/`

| File | Purpose |
|---|---|
| `01_OpenCode_Phase1_Refactor.md` | Phase 1 spec: reorganize the monolith into modules; preserve features, CLI, behavior; no optimization/redesign; output tree + migration plan + files + risk; **wait for approval**. |
| `02_OpenCode_Profile_Engine.md` | Phase 2 spec: `profile_engine` module converting CV/bio text to `UserProfile` dataclass; Pydantic; no LLM assumptions; every field has confidence; design only. |
| `03_OpenCode_Opportunity_DB.md` | Phase 3 spec: SQLAlchemy schema for opportunities (PhD/postdoc/Master/RA/faculty/industry); ER diagram + models + indexes + migration strategy; design only. |
| `04_OpenCode_Matching_Engine.md` | Phase 4 spec: deterministic matching engine (topic/method/programming/experience/funding/country/goal/competition/explainability); no LLM ranking; every score independently testable; design only. |
| `05_OpenCode_Email_Service.md` | Phase 5 spec: weekly digest; only score > 85; max 5 positions + 5 supervisors; why/deadline/funding/next action; architecture only. |
| `06_OpenCode_FastAPI.md` | Phase 6 spec: REST API (profile/matches/supervisors/opportunities/feedback/bookmark/email_preferences) + OpenAPI spec; design only. |
| `07_Kimi_Architecture_Critique.md` | Kimi prompt: criticize the backend as a principal architect at 1M-user scale; find weaknesses/bottlenecks/security risks; severity + why + how. |
| `08_Kimi_Rules.md` | Generic agent rules: don't invent requirements/features, stop on ambiguity, show options, recommend one, wait for approval. |

## `specs/`

| File | Content |
|---|---|
| `01_V1_Data_Contracts.md` | Field lists for `UserProfile`, `Opportunity`, `Supervisor`, `MatchResult` (incl. confidence everywhere). |
| `02_V1_Matching_Weights.md` | Starting weights (topic 30 / skill 20 / method 15 / advisor 15 / location 10 / funding 5 / competitiveness 5), tiering bands, deterministic-until-feedback rule. |
| `03_V1_Email_Digest_Format.md` | Digest contents (top 5 positions + 5 supervisors, fit score, explanation, deadline, funding, next action), tone, purpose. |
| `04_V1_API_Outline.md` | Endpoints (POST /profile, GET /matches, /supervisors, /opportunities, POST /bookmark, /feedback, /email_preferences) + response rule (include context + next action). |

## `phd_aggregator/` — the working prototype

| Path | What it is |
|---|---|
| `phd_aggregator.py` | The 7,368-line monolith (mapped below). |
| `config.yaml` | Runtime settings overlay (field_profile, countries, proxy, sources_enabled, freshness, seed, supervisor knobs, output). `field_profile: computer_science` is active here. |
| `applicant.yaml` | Personal data for email drafts (name/email/phone/education/publication/references). **Gitignored by convention but no `.gitignore` file exists in the repo yet.** |
| `applicant.example.yaml` | Placeholder template for `applicant.yaml`. |
| `seeds.txt` | Hand-picked position URLs (Nature Careers JSON-LD, EURAXESS OpenGraph, AJO plain HTML examples). |
| `test_supervisors.py` | Network sweep of the supervisor finder across every profile + subfield; `SUPERVISOR_TEST_COUNTRY` (default Germany), `SUPERVISOR_TEST_MIN` (default 5), `--whole-only`; exit 0 iff all targets yield candidates. |
| `CONTRIBUTING.md` | Extension contract: one function per source, one YAML per field; source isolation; politeness rules; no secrets; self-test must pass; worked examples (RSS source, seed adapter). |
| `README.md` | Feature-rich usage doc (quick start, four building blocks, Iran/restricted-network section, modes table, outputs, disclaimer). References `GETTING_STARTED.md` / `.fa.md`, `.env.example`, `.gitignore` — **none of which exist on disk**. |
| `requirements.txt` | Hard: `requests`, `requests[socks]`, `beautifulsoup4`, `feedparser`, `pandas`. Recommended: `pyyaml`, `lxml`. Optional: `curl_cffi`, `playwright`, `readability-lxml`. |
| `NotiIncluded.txt` / `notiIncludedtxt` | Two copies of the same personal seed/notification URL list (5 and 6 URLs, duplicated). Probably a manual-edit artifact. |
| `vpn.txt` | Persian V2Ray service signup/import instructions **including a live subscription URL** — sensitive, should not be in a public repo. |
| `Prompt_upgarade.txt` | The original 4-task prompt (supervisor finder, seed ingestion, adaptability, Cloudflare) + freshness addendum that drove the script's current features. |
| `fields/` | 11 profiles + template (see below). |

### `fields/` — per-field taxonomy (YAML, editable without touching Python)

| File | Lines | Notes |
|---|---|---|
| `template.yaml` | 126 | Fully-commented starter: tier semantics, weights, subfields, supervisor_source/topics/senior_signal. |
| `astronomy.yaml` | 991 | The reference profile (default). Core anchors (~150), context terms, negatives, weights 5/2.5/1/0.5/−2 threshold 2.0; `supervisor_source: ads`, `supervisor_ads_db: astronomy`, `supervisor_arxiv_cat: astro-ph*`, `supervisor_field: 31`, 11 curated OpenAlex topics, 7 subfields (ism, magnetism, cosmology, galaxies, exoplanets, stellar, radio), `departments:` registry (large, worldwide). |
| `physics.yaml` | 414 | General physics; `supervisor_source: ads`, `supervisor_field: 31`. |
| `condensed_matter.yaml` | 297 | `supervisor_source: ads`, `supervisor_ads_db: physics`, field 31. |
| `chemistry.yaml` | 401 | `supervisor_source: openalex`, field 16, senior_signal last_author. |
| `biology.yaml` | 457 | `openalex`, field 11. |
| `geology.yaml` | 451 | `openalex`, field 19. |
| `geophysics_hydro.yaml` | 338 | `ads`, physics db, field 19. |
| `mathematics.yaml` | 444 | `openalex`, field 26. |
| `computer_science.yaml` | 398 | **`require_title_anchor: true`** (strict gate), `openalex`, field 17. |
| `economics.yaml` | 394 | `openalex`, field 20, **`supervisor_senior_signal: none`** (alphabetical author order), subfields with `topics:` (macroeconomics, microeconomics, econometrics, development, international, …). |
| `engineering.yaml` | 493 | `openalex`, field 22. |

Shared profile structure: `name`, `description`, `core_anchors`, `context_terms`,
`negative_terms`, `search_terms`, `weights`, `threshold`, optional
`require_title_anchor`, `supervisor_source/ads_db/arxiv_cat`, optional
`supervisor_field/topics/senior_signal`, `subfields:` (label, keywords, optional
topics), optional `departments:` (country/institution/url/field_specific).

## `phd_aggregator.py` — internal map (line ranges)

### Header & config (1–633)
- `1–95`: module docstring (install, run modes, config layering, Iran/proxy
  notes, SOURCE STATUS LEGEND; endpoints verified July 2026).
- `97–176`: imports; hard deps fail fast; optional deps degrade gracefully
  (`_HAVE_YAML/_HAVE_PLAYWRIGHT/_HAVE_CURL_CFFI/_HAVE_FEEDPARSER/_HAVE_READABILITY`,
  `_HTML_PARSER`).
- `179–457`: **CONFIG block** — `CORE_ANCHORS` (202), `CONTEXT_TERMS` (291),
  `NEGATIVE_TERMS` (303), `RELEVANCE_WEIGHTS` (332), `RELEVANCE_THRESHOLD` (340),
  `SEARCH_TERMS` (345), `COUNTRIES` (352), `WANTED_POSITION_TYPES` (357),
  `KEEP_AMBIGUOUS` (359), `EXCLUDE_EXPIRED` (363), `SOURCES_ENABLED` (366, 18
  entries incl. stubs), `OUTPUT_PATH` (393), `WRITE_HTML` (394), `PROXY` (399)
  + more network/browser/supervisor/seed/freshness constants through 457.
- `622`: `OUTPUT_FIELDS` (16-column output schema).
- `633`: `@dataclass Config` — all runtime fields incl. `stem/csv_path/
  json_path/html_path/geo_filter_active` properties, compiled taxonomy slots
  `_core_rx/_context_rx/_negative_rx`.

### Config plumbing (742–1034)
- `742 _script_dir`, `749 _find_config_path`, `759 _load_yaml_file`,
  `778 load_field_profile`, `790 list_field_profiles`,
  `811 apply_field_profile`, `916 apply_config_yaml`, `1036 build_config`
  (3-layer merge + CLI overrides).

### Text & taxonomy (1348–1620)
- `1348 canonical_country` (canonical name + alias table), `1435 normalize_url`,
  `1455 _key_text`, `1462 dedupe_key`, `1480 make_record` (raw-record builder,
  every field defensive), `1535 compile_taxonomy` (builds regex tiers),
  `1541 score_relevance`, `1571 is_relevant`, `1643 classify_position_type`
  (phd/postdoc/faculty/staff/unknown; the "Post Doctoral" leak fix).

### Network (1819–2240)
- `1819 class Http`: shared requests Session, Retry/backoff, throttling,
  robots-aware GETs (`get`), plain `get_soup`, `get_feed`, `get_rendered`
  (Playwright, persistent context/profile, `domcontentloaded` + wait selector),
  `fetch_page` (full anti-bot chain), proxy detect/sweep, `close`.
- `2240`: `@register_source` decorator + source registry (`SOURCES` at 2252).

### Sources (2287–3928)
`@register_source` functions (each returns raw records; pipeline filters):
`euraxess` (2287 [HTML]), `nature_careers` (2387 [HTML]), `jobs_ac_uk` (2451
[HTML]), `findaphd` (2527 [JS], Cloudflare), `academictransfer` (2594 [JS], SPA
API interception), `academicjobsonline` (2693 [HTML]), `aas` (2751 [FEED/JS]),
`jrecin` (2796 [HTML]), `eso` (2873 [FEED RSS]), `esa` (2917 [HTML]), `iau`
(2965 [STUB]), `astrobetter` (2978 [STUB]), `linkedin` (3003 [HTML] guest
search), `uni_departments` (3418 [HTML], sweeps profile `departments:` or the
built-in `UNIVERSITY_DEPARTMENTS` registry), `seed_urls` (3849 [HTML], seed
file + sibling discovery via `@seed_adapter`). `UNIVERSITY_DEPARTMENTS` registry
lives near the uni_departments source.

### Parsing (3621–3928)
- `3621 parse_position_page`: JSON-LD JobPosting (`@graph` unwrapped) → OpenGraph/
  meta → readability main-text; returns standard records.

### Filtering / dedupe / freshness (3929–4600)
- `3929 filter_records`: order = type gate → relevance → expiry → region; logs
  per-drop counters; seed gate-bypass.
- `4051 dedupe_records`: pass 1 normalized URL, pass 2 title+institution;
  `_merge_into` merges richer metadata (institution/source wins) at 4076+.
- `4169 apply_freshness`: effective-date derivation (deadline → posted →
  first_seen from state → page_date), `max_age_days` stale-drop,
  `freshness` label per record; `load_state`/`save_state` for
  `.seen_positions.json`.

### Career toolkit (4602–5710)
- `4602 build_email`, `4648 write_emails` (per-position drafts + index),
  `4841 find_professors` (curated + live-arXiv survey → professors.md/.csv),
  `5054 write_scholarships` (curated list matched to profile), `APPLICANT_PROFILE`
  loaded from `applicant.yaml`.

### Supervisor finder (5711–6311)
- `5711 aggregate_supervisors` (name-variant merge, senior-author signal,
  country filter, min-papers), `_supervisor_chain` (source selection logic),
  `ads_supervisor_docs`, `openalex_supervisor_docs`, `arxiv_supervisor_docs`,
  `openalex_supervisor_authors` (author-direct: h-index + recency + in-country
  scoring), `_supervisor_focus`, `_oa_field_id`, `_CANON_TO_ISO2`,
  `find_supervisors` (6077, writes supervisors_<field>_<country>.{csv,json,html}),
  `AUTHOR_SEARCH_FMT`.

### Orchestration & CLI (6312–7368)
- `6312 run`: iterate enabled sources → filter → freshness → dedupe → sort →
  `mark_new` vs previous JSON → `write_outputs` → `print_summary`;
  `injected_raw` for offline tests.
- `6364 _sample_records` + `6482 self_test`: two-pass hermetic test (astronomy
  taxonomy pinned, separate state path); ~100 assertions.
- `7075 parse_args`: full CLI (`--list-sources`, `--list-fields`, `--new-field`,
  `--source`, `--country`, `--field`, `--find-supervisors`,
  `--supervisor-source`, `--years-back`, `--seeds`, `--max-age-days`,
  `--no-config`, `--keyword`, `--threshold`, `--output`, `--proxy`,
  `--no-proxy-detect`, `--limit-per-source`, `--no-robots`, `--no-html`,
  `--no-headed`, `--include-expired`, `--phd-only`, `--browser-profile`,
  `--fresh-profile`, `--challenge-wait`, `--write-emails`, `--find-professors`,
  `--scholarships`, `--extras`, `--no-fetch`, `--self-test`, `--debug`).
- `7167 do_list_sources`, `7181 new_field_wizard` (interactive profile
  scaffolder), `7298 main`.

## Current run path (quick trace)

`main` → `build_config` (3-layer) → (self-test | find-supervisors | run) →
`run` loops `SOURCES` → `make_record` → `filter_records` →
`apply_freshness` (+state) → `dedupe_records` → `mark_new` →
`write_outputs` (CSV/JSON/HTML) → `print_summary`.

## Notes on hygiene gaps (details in QUICK_WINS / QUESTIONS)

- `vpn.txt` contains a live subscription URL; `applicant.yaml` contains real
  personal data; `NotiIncluded.txt`/`notiIncludedtxt` duplicate. No `.gitignore`
  exists to protect any of these if the repo goes public.
- `README.md` (aggregator) links `GETTING_STARTED.md`/`.fa.md`, `.env.example`,
  `.gitignore` that don't exist on disk.
