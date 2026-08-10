# QUESTIONS_FOR_FOUNDER.md

Ambiguities found during the full read that need a founder decision. Per the
operating rules: each states the ambiguity, lists options, and recommends one.
Nothing here was silently assumed. Order = importance.

---

## Q1. Phase 1 scope: reorganize the monolith, or also start the platform?

**Ambiguity.** `docs/00` says "Implement Phase 1 only", and `prompts/01` says
Phase 1 is a pure refactor with **no new features**. But `docs/04` calls Phase 1
"turn the current scripts into a maintainable system" and `docs/03`'s launch
sequence step 1 is "clean up the existing script base". Meanwhile `config.yaml`
already points at `computer_science` and the profile/toolkit code already goes
well beyond the astronomy-only docs.

**Options.**
1. (Recommended) Phase 1 = refactor only, exactly as `prompts/01`: monolith →
   modules, preserve behavior and CLI, wait for approval, add per-module tests.
2. Phase 1 = refactor + the first platform seam (e.g. also design the
   `profile_engine` dataclass now).
3. Phase 1 = refactor + immediate DB/API work (contradicts the roadmap).

**Recommendation:** Option 1. The release rule ("don't start the next phase
until the previous is stable") supports a clean refactor first.

---

## Q2. The config default: astronomy or computer_science?

**Ambiguity.** The built-in CONFIG block + `fields/astronomy.yaml` are the
"reference" astronomy setup, but `config.yaml` currently sets
`field_profile: computer_science` (strict `require_title_anchor`). A bare
`python phd_aggregator.py` therefore runs a CS hunt, not astronomy.

**Options.**
1. Keep `computer_science` (matches the founder's current hunt).
2. (Recommended) Restore `astronomy` as the shipped default and leave a
   commented `computer_science` line, so the reference default matches the
   docs; founder re-selects CS with `--field computer_science` or by editing
   the one line.
3. Leave as-is but add a comment documenting intent.

**Recommendation:** Option 2 — documentation/reference consistency, one line.

---

## Q3. Going public: what's the target repo shape and what's already public?

**Ambiguity.** `Prompt_upgarade.txt` says "I'm making this repo PUBLIC on
GitHub" and requires it to be "clean and adaptable". But the repo currently
contains `applicant.yaml` (real personal data), `vpn.txt` (live subscription
URL with embedded credentials), duplicated personal link files, `__pycache__`,
and run artifacts — with **no `.gitignore`**.

**Options.**
1. (Recommended) Before any push: add `.gitignore` (QUICK_WINS #1), remove/
   untrack `vpn.txt` and the duplicate noti files, keep `applicant.example.yaml`.
   Then Phase 1 refactor on the clean repo.
2. Push as-is and clean later (risky: personal data + credentials would leak).
3. Create a fresh public repo and copy only the sanitized content.

**Recommendation:** Option 1.

---

## Q4. Missing referenced files: `GETTING_STARTED.*`, `.env.example`

**Ambiguity.** `phd_aggregator/README.md` links `GETTING_STARTED.md` (and
`.fa.md`) and instructs `cp .env.example .env`; none of these files exist.
Either the docs are stale or the files were never created.

**Options.**
1. (Recommended) Create `GETTING_STARTED.md` (+ `.fa.md`) and `.env.example`,
   matching the README's described behavior.
2. Remove the dead links from the README.

**Recommendation:** Option 1 — the beginner guide is referenced as the entry
point for non-programmers and the founder is exactly that user.

---

## Q5. LinkedIn source: robots.txt override is documented — is it acceptable for v1?

**Ambiguity.** The `linkedin` source (enabled by default in `config.yaml` and
`SOURCES_ENABLED`) uses the public guest search and **overrides robots.txt** for
those queries, per its docstring/README disclaimer. `docs/06` and
`CONTRIBUTING.md` both make politeness "non-negotiable" (no robots bypass, no
login-walled scraping).

**Options.**
1. (Recommended) Keep it enabled but default `linkedin: false` in
   `config.yaml` (opt-in), preserving the code for those comfortable with it.
2. Keep enabled as-is (personal use, low volume) and document why.
3. Remove the source entirely.

**Recommendation:** Option 1 — resolves the politeness contradiction while
keeping the capability. Needs founder sign-off because it touches behavior.

---

## Q6. Which "customer" does Phase 1 serve: the founder's own job hunt, or a product?

**Ambiguity.** The code is heavily personalized: `applicant.yaml`, curated
`PROFESSOR_SEED`, `SCHOLARSHIPS`, `UNIVERSITY_DEPARTMENTS` (Germany-heavy),
astro-focused default. The docs describe a general product for many users.

**Options.**
1. (Recommended) Phase 1 keeps the personal instance working exactly as now;
   the multi-user product starts in Phases 2–3 (profile engine + DB).
2. De-personalize now (replace curated lists with placeholders, drop
   applicant-specific defaults).

**Recommendation:** Option 1 — preserves behavior (core requirement) and
defers the product turn to the phases that introduce real users.

---

## Q7. Supervisor finder's ADS dependency: token flow confirmation

**Ambiguity.** For astronomy/physics, `supervisor_source: auto` prefers NASA
ADS, which needs `ADS_API_TOKEN` from a gitignored `.env`. Without it the chain
falls back to OpenAlex/arXiv. The README documents the token flow.

**Options.**
1. (Recommended) Keep as-is (documented graceful degradation) and just ship
   `.env.example` (QUICK_WINS #4).
2. Make OpenAlex the default for everything (drops the best astro index).
3. Require the token (breaks tokenless UX).

**Recommendation:** Option 1.

---

## Q8. Contact-email policy for supervisors

**Ambiguity.** `Prompt_upgarade.txt` says "contact email ONLY if publicly listed
on their institutional page — never guess or fabricate". The implemented code
(per README) takes emails only from public ORCID records.

**Options.**
1. (Recommended) Keep ORCID-only (safer, machine-readable).
2. Also scrape institutional pages for emails (more coverage, more failure +
   politeness surface).

**Recommendation:** Option 1.

---

## Q9. Deterministic ranking vs. the "competitiveness" dimension in specs

**Ambiguity.** `specs/02` and `prompts/04` add a "competitiveness" dimension
(e.g. applying success rates), and Phase 6 mentions feedback-driven tuning.
The current script has no such data and the docs demand deterministic ranking.

**Options.**
1. (Recommended) Phase 4 implements competitiveness as a deterministic
   rule-based factor (e.g. funding-source type, institution tier), no model
   learning; revisit only after real feedback.
2. Defer competitiveness entirely until data exists.
3. Use a learned model early (contradicts the docs).

**Recommendation:** Option 1 — implementable deterministically now.

---

## Q10. Who reviews and approves Phase 1's module-boundary decisions?

**Ambiguity.** `prompts/01` says "wait for approval" before writing code, and
the migration splits are architecture decisions (MIGRATION_PLAN.md).

**Options.**
1. (Recommended) Founder approves MIGRATION_PLAN.md as-is; I proceed step-by-step,
   each step self-test-green, and pause at any deviation.
2. Founder reviews each module boundary before implementation.

**Recommendation:** Option 1 — plan is explicit; per-step gates make course
corrections cheap.

---

## Summary of recommended defaults (if the founder wants to fast-track)

1. Phase 1 = pure refactor (Q1).
2. Restore `astronomy` default, commented CS line (Q2).
3. Add `.gitignore`, strip personal data before any public push (Q3).
4. Create `GETTING_STARTED.*` + `.env.example` (Q4).
5. `linkedin: false` by default (Q5).
6. Keep personal instance behavior; product turn in Phases 2–3 (Q6).
7. Keep ADS graceful fallback + `.env.example` (Q7).
8. Keep ORCID-only emails (Q8).
9. Deterministic competitiveness rule in Phase 4 (Q9).
10. Approve MIGRATION_PLAN.md, proceed step-by-step (Q10).
