# PROJECT_UNDERSTANDING.md

Lead-engineer summary of what this project is, what exists today, and how the
existing code relates to the planned platform. Written from a full read of
`docs/`, `prompts/`, `specs/`, and the entire `phd_aggregator/` prototype.

## 1. One-sentence mission

A career intelligence platform that reads a user's background, builds an
accurate structured profile, and recommends the few best-fit opportunities and
supervisors — **explaining why each fits and what to do next** — instead of
dumping a long list of search results.

## 2. The product (from the docs)

- **Who it serves:** PhD applicants, research-heavy Master's applicants,
  postdocs, research engineers, specialized technical professionals.
- **What it does:** intake (paste bio/CV + optional ORCID/Scholar/LinkedIn/
  site links + field/region/funding preferences) → profile extraction →
  opportunity matching (positions, supervisors, labs, funded openings) →
  explainable ranking → weekly email digest (≤5 positions, ≤5 supervisors,
  high-fit only) → shortlist tracking (saved/contacted/applied/interview/
  rejected/accepted).
- **What it is NOT at first:** a social network, a marketplace, a generic
  search engine, or a job-board clone. Success is fit quality, trust, and
  clarity — not result count.
- **Design principle:** the LLM should *support* the system, not *define* it.
  LLM is used only for extraction, summarization, explanation, and drafting.
  Ranking must stay **deterministic**.
- **Success metrics:** profile completion, email open/click-through, save rate,
  return rate, and positive feedback on recommendation relevance.

## 3. Target architecture (v1)

Three subsystems on top of a data layer:

1. **Knowledge Engine** — continuously discovers and normalizes opportunities,
   supervisors, institutions, and topics (university pages, OpenAlex, boards…).
2. **Identity Engine** — converts raw text / CV / links into a structured
   profile.
3. **Intelligence Engine** — computes explainable matches between profile and
   opportunities.

Data flow: ingest → normalize → build profile → score → explain → digest →
feedback. Matching dimensions: topic / method / skill / experience / location /
funding / competitiveness.

Recommended stack (docs): Python, FastAPI, SQLite first, SQLAlchemy, Next.js,
Tailwind, shadcn/ui. Suggested v1 weights: topic 30%, skill 20%, method 15%,
advisor 15%, location 10%, funding 5%, competitiveness 5%. Tiering: 90–100
strong, 75–89 good, 60–74 stretch, <60 excluded by default.

## 4. What already exists (the reality on disk)

The working code today is **one 7,368-line file**: `phd_aggregator/phd_aggregator.py`.
It is a mature, self-contained, polite crawler + scorer + reporter, NOT a
throwaway script. It already implements a large slice of the Knowledge Engine
and part of the Intelligence Engine:

- **Aggregation:** 13 live sources (`@register_source`), plus stubs — EURAXESS,
  Nature Careers, jobs.ac.uk, FindAPhD, AcademicTransfer, AcademicJobsOnline,
  AAS Job Register, JREC-IN, ESO, ESA, LinkedIn guest search, `uni_departments`
  sweeps, and `seed_urls` (hand-picked links + sibling discovery).
- **Multi-field:** 10 shipped field profiles (`fields/*.yaml`) + `template.yaml`;
  subject knowledge lives in YAML, not Python. `computer_science` is selected in
  `config.yaml` today.
- **Relevance engine:** tiered taxonomy (core anchors / context terms /
  negative terms) with a deterministic weighted score
  (`core_title 5 / core_desc 2.5 / context_title 1 / context_desc 0.5 /
  negative −2`, threshold 2.0). Keep iff ≥1 core anchor AND score ≥ threshold.
- **Type gate:** position-type classifier (phd/postdoc/faculty/staff/unknown),
  strict PhD-only mode, ambiguous-keep option.
- **Geo filter:** canonical-country map + country guessing + alias table.
- **Dedupe:** two passes (normalized URL, then title+institution) with merge.
- **Freshness:** effective date from deadline → posted → first-seen (state file)
  → page date; `max_age_days` drops stale undated posts.
- **Outputs:** CSV + JSON + self-contained HTML dashboard (search/filter/sort,
  NEW badges), per-run summary with keep/drop reasons.
- **Career toolkit extras:** per-position application-email drafts
  (`--write-emails`), curated + live-arXiv professor list (`--find-professors`),
  scholarship shortlists (`--scholarships`).
- **Supervisor finder** (`--find-supervisors`): ranked PI search for ANY major —
  OpenAlex (no token, all fields) → NASA ADS (astro/physics, token) → arXiv
  (tokenless). Two paths: keyword-matched papers aggregated by author, and an
  **author-direct** OpenAlex path (curated topics + country + h-index/recency/
  in-country scoring).
- **Network resilience:** everything through a single configurable proxy
  (`socks5h://127.0.0.1:10808` default), proxy auto-detection with local-port
  sweep, layered anti-bot fallback (requests → curl_cffi → Playwright headless →
  headed), persistent browser profile, robots.txt, throttling, retries+backoff.
- **Self-test:** an offline two-pass `--self-test` (~460 lines of assertions)
  that must pass; also a `test_supervisors.py` network sweep.

## 5. How the existing code maps to the target

| Target subsystem | Already exists in the script | Gap to close |
|---|---|---|
| Knowledge Engine | Sources, parsing, dedupe, freshness, supervisor finder, OpenAlex/ADS | Database instead of JSON; scheduled ingest; institutional/topic graph |
| Identity Engine | `applicant.yaml` profile (used for emails) | Real profile extraction from CV text (dataclass, confidence per field, Pydantic) |
| Intelligence Engine | Relevance scoring, supervisor ranking (deterministic) | Multi-dimension match (skill/method/advisor/location/funding/competition) + explanations |
| Delivery | HTML dashboard, emails, JSON/CSV | FastAPI + SQLite/SQLAlchemy + Next.js frontend, weekly scheduler |

The script's deterministic core (tiered taxonomy, weights, thresholds) is the
seed of the Intelligence Engine; its crawlers are the seed of the Knowledge
Engine; `applicant.yaml` is a static stand-in for the Identity Engine.

## 6. Config layers (later beats earlier)

1. CONFIG block at the top of `phd_aggregator.py` (built-in defaults; contains
   the multi-major default taxonomy).
2. `config.yaml` — runtime settings (proxy, sources, countries, freshness,
   seed options, field_profile, supervisor knobs). Everything optional.
3. `fields/<profile>.yaml` — field-specific knowledge (anchors, weights,
   subfields, departments, supervisor topics). Selected via `field_profile` or
   `--field`.
4. CLI flags — override everything.

Secrets (ADS token) come from env / gitignored `.env`; personal data from
gitignored `applicant.yaml`.

## 7. Operating rules that govern any change (from docs/06 + prompts/08)

- Preserve behavior unless a change is explicitly requested.
- Keep ranking deterministic; keep every task independently testable.
- Do not redesign the whole system at once; break the monolith into modules
  **gradually**, not in one risky jump.
- Don't start the next phase until the previous one is testable and stable.
- A source that breaks logs a warning and is skipped — never crashes a run.
- No secrets in the repo; no CAPTCHA solving / ban evasion; robots.txt +
  politeness are non-negotiable.
- If a requirement is ambiguous: state it, show options, recommend one, wait
  for approval.

## 8. Roadmap summary (docs/04)

- **Month 1:** Phase 1 refactor monolith → modules; Phase 2 structured profile
  extraction; Phase 3 opportunity DB schema; Phase 4 deterministic matching;
  Phase 5 email digest; Phase 6 first REST API.
- **Month 2:** dashboard, shortlist tracking, bookmarking, feedback.
- **Month 3:** explainability, taxonomy, more sources, dedupe.
- **Month 4:** private beta, digest tuning, recommendation evaluation.
- **Month 5:** public free launch, donation support, onboarding.
- **Month 6:** feedback-driven ranking; expand beyond PhD roles.

## 9. Key facts / numbers worth remembering

- Script: `phd_aggregator.py`, 7,368 lines, ~358 KB. Fully read.
- 13 sources on by default; 4 stubs off (`iau`, `astrobetter`, `china`,
  `korea`, `new_zealand` — `china` listed separately). Note: README/config
  refer to IAU/AstroBetter as stubs.
- 10 field profiles: astronomy (default/reference, 991 lines), biology,
  chemistry, computer_science, condensed_matter, economics, engineering,
  geology, geophysics_hydro, mathematics, physics + template.
- Default astronomy taxonomy: 3 tiers of prefix-matched terms; CMB/ISM/ALMA/
  LOFAR/LIGO etc. are ALL-CAPS case-sensitive whole-word matches.
- Output schema (`OUTPUT_FIELDS`, 16 cols): title, institution, country,
  deadline, posted_date, effective_date, age_days, freshness, url, source,
  relevance_score, matched_anchors, matched_keywords, short_description,
  position_type, is_new.
- Dependencies: hard = requests, beautifulsoup4, feedparser, pandas; optional =
  pyyaml, lxml, curl_cffi, playwright, readability-lxml. SOCKS support comes
  from `requests[socks]`.
- `test_supervisors.py` sweeps every profile + subfield for candidates against a
  country (default Germany), exit 0 iff every target yields ≥1 candidate.
- The docs mention `GETTING_STARTED.md`/`.fa.md`, `.env.example`, `.gitignore`,
  and a `phd_aggregator/` README with file links — several of these referenced
  files do not currently exist on disk (see QUESTIONS_FOR_FOUNDER.md).

## 10. Notable engineering strengths

- Defense-in-depth: per-source isolation, per-field defensive parsing, graceful
  optional-dep degradation, graceful proxy failure, polite anti-bot layering.
- Testability: hermetic offline self-test with its own state path; injected_raw
  run mode; the supervisor sweep test reuses the real pipeline.
- Extensibility without touching Python: YAML profiles + template + wizard
  (`--new-field`); ~15-line new sources; trivial seed adapters.
- Deterministic, explainable scoring with explicit tier semantics and
  documented edge cases (postdoc-with-PhD-wording, crossovers, ambiguous level).
