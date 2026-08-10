# QUICK_WINS.md

Small, safe, behavior-preserving improvements found while reading the code.
Each is independent, low-risk, and does not change what the pipeline produces.
Ordered roughly by value ÷ effort. Nothing here is a feature change — if any
item turns out to need product decisions, it moves to QUESTIONS_FOR_FOUNDER.md.

## 1. Add a `.gitignore` (protects a public repo — highest priority)

The README and CONTRIBUTING both say `applicant.yaml`, `.env`, `.pw_profile`,
`.seen_positions.json`, `__pycache__` are "gitignored" — **but no `.gitignore`
exists anywhere in the repo** (only `.codegraph/.gitignore`). The repo is
intended to go public (`Prompt_upgarade.txt`: "I'm making this repo PUBLIC on
GitHub"). Right now a single `git add .` would commit:
- `applicant.yaml` (real name, phone, emails of the founder),
- `vpn.txt` (a live V2Ray subscription URL with embedded credentials),
- `NotiIncluded.txt` / `notiIncludedtxt` (personal seed links),
- `__pycache__/`, run artifacts (`phd_positions.*`, `.seen_positions.json`,
  `emails/`, `supervisors_*`, `professors.*`, `scholarships.*`, `.pw_profile`).

Add one `.gitignore` at the repo root covering those + `.env*` + `*.pyc`
etc. **Do not touch `applicant.example.yaml` or `*.example.*`.**

## 2. Remove or safely relocate `vpn.txt`

Contains a live subscription URL — a credential, not documentation. If the
subscription link is needed for personal use, keep it out of the repo
(un-track or add to `.gitignore`). The proxy settings it documents are already
covered by the README + module docstring.

## 3. Dedupe the notification lists

`NotiIncluded.txt` and `notiIncludedtxt` are near-identical (5 vs 6 URLs, one
of them duplicated). Keep one canonical file (or move the URLs into
`seeds.txt`, which they closely resemble), delete the other.

## 4. Create the referenced-but-missing docs

`phd_aggregator/README.md` links to `GETTING_STARTED.md` (English + `.fa.md`)
and `.env.example`, and the README/disclaimer reference `.gitignore` — none of
those files exist on disk. Options: (a) create `GETTING_STARTED.md` /
`.fa.md` / `.env.example` per the README's described behavior, or (b) remove
the dead links. Recommend (a) — the beginner guide was promised and the founder
is a non-programmer-facing user of this project. Confirm scope with founder.

## 5. Verify `field_profile` intent in `config.yaml`

`config.yaml` currently selects `field_profile: computer_science`, which is
`require_title_anchor: true` and non-astro. The built-in default (and the whole
reference profile) is astronomy. If the current default run is meant to be CS,
fine — otherwise this changes what a bare `python phd_aggregator.py` returns
and is worth a one-line comment or an explicit decision (see QUESTIONS).

## 6. Add `.env.example` (ADS token bootstrap)

README documents `cp .env.example .env` but the file doesn't exist. A small
template with `ADS_API_TOKEN=` + a comment (and `V2RAY/other` knobs if desired)
completes the documented flow. No secrets — only the key name.

## 7. Requirements hygiene

- `requirements.txt` lists `requests[socks]` under "Core" while README says
  only `requests / beautifulsoup4 / feedparser / pandas` are hard. Align the
  comment (socks support is needed whenever `PROXY` is a `socks5h://` URL, so
  it is effectively required for the default setup — just document why).
- `feedparser` is imported as optional (`_HAVE_FEEDPARSER`) but listed as hard
  in requirements — harmless, but the optional-import guard suggests it could
  be demoted. Confirm intent.

## 8. Remove the duplicate `applicant.yaml` fields comment drift

`applicant.example.yaml` mentions a sentence inside `build_email()` that may be
deleted — that's fine, but the comment should name the actual function now that
emails live in `write_emails`/`build_email` (already correct post-Task). Minor
doc-only tweak.

## 9. Lock the pinned "verified" endpoint notes

Source docstrings say "verified live in July 2026" and keep endpoint/selector
constants in clearly-marked spots (a documented convention). Quick win: add a
tiny checklist in CONTRIBUTING (already exists) and a `grep "verified"`-style
smoke test that fails if any source's "verified" note is older than N months —
turns endpoint drift into a visible signal instead of a silent empty source.

## 10. Keep the CSV/JSON/HTML outputs out of version control

Even with `.gitignore` (item 1), consider documenting the expected artifacts in
the root README's "outputs" section so future contributors know run outputs are
regenerable and intentionally untracked. Doc-only.

## 11. Consistent naming of the stray case files

`NotiIncluded.txt`, `notiIncludedtxt`, `Prompt_upgarade.txt` have
inconsistent casing/trailing-ext spelling. After item 3, normalize names to
lowercase snake_case (e.g. `seeds.md`, `prompt_upgrade.md`) or move the
content into `docs/`/`prompts/`.

## 12. Add a single "dev sanity" script

A one-liner documented in README: `python phd_aggregator.py --self-test &&
python test_supervisors.py --whole-only` as the pre-commit gate. Behavior-neutral;
just makes the existing gates discoverable. (Any real CI can wait for Phase 1.)

## Anything that touches behavior → not a quick win

Changes to scoring, taxonomy, sources, output schema, CLI, or politeness are
deliberate product/engineering decisions — see MIGRATION_PLAN.md (Phase 1) and
QUESTIONS_FOR_FOUNDER.md, not this list.
