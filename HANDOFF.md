# HANDOFF — progress report (2026-08-14)

Everything in your correction list is done. Branch **`chore/audit-repair`** →
**PR #1** (https://github.com/mimdot/CIK/pull/1), all pushed, **CI green**.

**Tests: 726 → 945 backend, 97 → 147 dashboard.** 17 commits, 173 files.

Companion docs: `ISSUES.md` (findings, decisions, §D2 the API-keys/admin
report, §D3 live verification, §D4 the last three items), `ARCHITECTURE.md`
(§6 = the full astronomy-hardcoding inventory with file:line).

---

## 1. Your list, item by item

| You said | What it actually was | Status |
|---|---|---|
| "the engine is focused on astronomy whatever field I pick" | `fetch_sources` read **one global source list** and `apply_field_profile` never touched it; **and** 4 "general" boards had astronomy URLs/facets/keywords hardcoded inside them | **fixed at both levels** |
| "I need a cancel option, not exit" | `cancel_job` only cancelled jobs that had **not started**; a running crawl ignored it and its results were thrown away | **fixed** — cooperative, keeps partial results |
| "the 13th source is very time consuming" | `uni_departments`: **150 pages ≈ 5 min of delays alone** for astronomy | **opt-in, OFF by default** + instant browse-it-yourself alternative |
| "PhD and Postdoc need separate options" | types were hardcoded dicts, so only one blended list was possible | **separate searches**; Master's/Scholarships shipped disabled |
| "add auto-correct for countries and universities" | a 53-entry hand-written map; **no** institution normalisation at all | **full ISO-3166 (249) + fuzzy**, on input *and* scraped data |
| "18 open positions vs 63 records" | **four** independent causes (see §2) | **fixed**, with a visible breakdown |
| "PDF support needs a parser" | deps were already in `requirements.txt` — your API ran under a **different Python** | **fixed**; no message ever tells you to pip install |
| "Could not extract profile from text" | `extract_profile` calls an **LLM**; no API key = dead end. **Your hunch was right.** | **fixed** — token-free extractor |
| "think about selecting keywords instead of CV" | did not exist | **built** — the keyword picker is now the primary path |
| "supervisors limited to 25 per field" | `author_enrich = 25` in the interactive path | **100**, and settable |
| "non-related field results, exports too" | scoring alone could not sink an off-field researcher | **gated out**; export shares the same filtered set |
| "the fit value is strange / not usable" | raw unbounded score, **and** the UI printed `fit*100 + "%"` → a 43 showed as **"Fit 4300%"** | **explainable 0-100**, calibrated |
| "the Field profile setting confuses me" | it leaked `--field`, **and it was a fake control** (local state only, reset on reload) | **rewritten + made real** |
| "weekly digest — say it's for next update" | — | **"Coming soon"** |
| "why are API keys and Admin in my dashboard?" | **nothing vestigial** — both are complete working features | **hidden from normal users**, nothing deleted (report: `ISSUES.md` §D2) |
| "searching looks frozen / static" | progress existed but **no results** until the end | **results stream in**, first at 0.27s of a 0.38s run |
| "testimonials / donation for next update" | — | **placeholders added** (empty on purpose) |
| "add my GitHub and email" | — | **footer on dashboard + public pages** |
| "the repo is ~8GB" | **`.git` is 3.72 MiB.** The 8 GB is all gitignored build output | **nothing to do** — see §3 |
| "fix the failing CI" | pytest was **never installed**, so your 726 tests never ran; plus a real in-place-sort bug | **all jobs green** |

---

## 2. The three findings worth remembering

**The 18-vs-63 count had four independent causes**, not one:
1. nothing explained the shrink (`filter_records` computed exact drop counts, then threw them away into a log line);
2. **`Opportunity.field` was never written** — the column existed but records were never stamped, so the database could not tell an astronomy row from a chemistry one. *This is a second, independent reason chemistry searches showed astronomy results.*
3. the opportunity cache was one global key with a 1-hour TTL;
4. a failed DB save was swallowed **and** skipped cache invalidation.

You now see `63 found → 41 after field filter → 22 after dedupe → 18 stored`
with the reason for every drop.

**Your 8 GB repo needs no surgery.** `.git` is **3.72 MiB** — the entire
history. The bulk is `dashboard/src-tauri` (5.9 G Rust target), `node_modules`
(789 M) and PyInstaller `build/`+`dist/` (743 M), all already gitignored. I
verified with `git check-ignore`: **`.gitignore` needed no changes.** No
filter-repo, no BFG, no fresh repo. A fresh clone is under 4 MB.

**FindAPhD could not be verified.** Cloudflare returns 403 for *every*
discipline slug from your exit IP — including the two astronomy ones that have
always shipped. Per your no-evasion rule I left it data-driven and flagged it
in the code rather than working around the block. Switching V2Ray server
usually helps.

---

## 3. How to test it

### Web app (do this first)

```bash
# Terminal 1 — backend.  IMPORTANT: use the SAME Python that has the deps.
cd phd_aggregator
python3 -m pip install -r requirements.txt -r requirements-dev.txt
CIK_COOKIE_SECURE=0 CORS_ORIGINS=http://localhost:3000 \
  python3 -m uvicorn api.app:app --reload --port 8000

# Terminal 2 — dashboard
cd dashboard && npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # -> localhost:3000
```

> The "PDF support needs a parser" message you hit was **an environment
> split**: your venv had `pdfplumber`, the Python running the API did not.
> `python3 -m pip` (not bare `pip`) guarantees they match. The app now also
> tells you up front what it can read, at `/api/profile/parser-support`.

Make sure V2RayN is running (SOCKS `127.0.0.1:10808`).

### Click-through checklist — what to look for, and what is WRONG

Work down the list. Each row says what you should see; anything else is a bug
worth reporting.

**1. Opportunities — the position type (2C)**
- [ ] Tabs at the very top: **PhD**, **Postdoc**, and **Master's** /
      **Scholarship** greyed out with a "Coming soon" chip.
- [ ] Clicking a greyed tab does nothing. PhD is selected by default.
- [ ] Switching to **Postdoc** changes the headline to
      "N open postdoc positions" and reloads the list.
- ✗ WRONG: one blended list, or Master's being clickable.

**2. Opportunities — the field and subfields (1A/1B)**
- [ ] Choose **Chemistry**. A note appears: *"No board is dedicated to
      Chemistry yet…"* — that is correct and expected.
- [ ] Click **Narrow by subfield** — groups are collapsed until you ask.
      Tick two; they appear as removable chips.
- [ ] Switch the field to Astronomy: **the subfield chips clear**.
- ✗ WRONG: subfields surviving a field change (they mean different things).

**3. Opportunities — running a search (2A/6A)**
- [ ] Press **Search for positions**. The dialog shows, live:
      per-source status (done / error / skipped), **elapsed time**,
      **"Found so far"**, and **positions listed as they arrive** — not a
      frozen bar.
- [ ] Press **Cancel search** mid-run. It says *"Stopping — finishing the
      source in flight…"*, then *"Search stopped. The positions found before
      you cancelled have been kept."*
- [ ] The app is still usable; the kept results are in the list.
- [ ] On a full run, read the breakdown: `63 found → 41 after field filter →
      22 after dedupe → 18 stored`, with reasons underneath.
- ✗ WRONG: the app closing, needing a restart, or losing what it found.

**4. Opportunities — the slow sweep (2B)**
- [ ] The "Also sweep university department pages" checkbox is **OFF** and
      says it adds **several minutes**.
- [ ] Click **"Or browse the department list yourself (instant)"** — filter by
      country, search by name, open one. No crawling, no waiting.

**5. Profile — keywords first, CV optional (3A/3B/3C)**
- [ ] The page leads with **field → keywords**, not with a CV box.
- [ ] Keyword groups are collapsed; search filters across them and
      auto-expands matches; "All" selects a whole subfield; chips are
      removable; "Add your own" works. **No AI key is needed for any of this.**
- [ ] Expand *"Optional: pre-fill from a CV"*, paste some CV text, press
      **Pre-fill my keywords** — matching keywords get ticked above.
- [ ] Upload a **PDF**. It should read. If this installation cannot, it says
      so plainly and points you at pasting — it must **never** tell you to run
      `pip install`.
- [ ] Paste nonsense and pre-fill: you get a *reason* ("No research field
      could be recognised…"), never a bare "Could not extract profile".

**6. Supervisors — auto-correct, fit, export (2D/4A/4B/4C)**
- [ ] Type `Germny` in **Country** → *"Did you mean Germany?"*. It **suggests**;
      it must not silently rewrite what you typed.
- [ ] Try `UK`, `Holland`, `Kazakhstan`, and a nonsense word (which should warn).
- [ ] Run a search. Scores are **`Fit 72 / 100`**, never a percentage over 100.
- [ ] Expand a card: it explains *how* the score was reached
      ("29 pts — matches your terms: …; 20 pts — senior author on 5 of 9…").
- [ ] **Export CSV** and open it: exactly the rows on screen, explanations
      included.
- ✗ WRONG: "Fit 4300%", a bare number with no explanation, or an export
  containing rows you filtered out.

**7. Settings (5A/5B/5C)**
- [ ] The field control shows **your saved field**, and changing it saves.
- [ ] Search the page for `--field` or "pipeline runner" — **nothing**.
- [ ] Digest is labelled **Coming soon**.
- [ ] **Admin** and **API Keys** are absent from the navigation. To see them:
      `python3 phd_aggregator.py --make-admin you@example.com`, then reload.

**8. Footer (6D)** — GitHub and your email appear on every page, dashboard and
public, and both are clickable.

### CLI

Fastest confidence check — needs no network, takes two seconds:

```bash
cd phd_aggregator
python3 phd_aggregator.py --self-test     # must end: >>> SELF-TEST: ALL PASSED
```

See exactly which boards a run WILL use, before running it:

```bash
python3 phd_aggregator.py --field chemistry --list-sources
```

```
[---] aas                  not relevant to chemistry     <- the headline fix
[---] eso                  not relevant to chemistry
[on ] euraxess
[opt] uni_departments      slow — add --include-slow-sources
```

Then run real searches:

```bash
# PhD only, then postdocs only — the two must not mix
python3 phd_aggregator.py --field chemistry --type phd     --limit-per-source 5
python3 phd_aggregator.py --field chemistry --type postdoc --limit-per-source 5

# opt in to the slow department sweep (adds minutes)
python3 phd_aggregator.py --field chemistry --include-slow-sources

# supervisors
python3 phd_aggregator.py --find-supervisors --field chemistry --country Germany
```

Open the resulting `phd_positions.csv` and check the `field` and
`position_type` columns are all what you asked for.

Run the test suite yourself:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -q        # expect: 960 passed
```

### Desktop app — **this part is yours**

I could not click through it: no display in my environment. Build it with:

```bash
cd phd_aggregator
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller cik-api.spec --noconfirm      # -> dist/cik-api, ~159 MB
cp dist/cik-api ../dashboard/src-tauri/sidecar/api/cik-api-$(rustc -vV | sed -n 's/host: //p')
cd ../dashboard && npm run tauri:build               # or tauri:dev to just run it
```

**The sidecar is now 159 MB, down from 346 MB.** If your build comes out much
larger, the excludes in `cik-api.spec` did not apply — tell me.

Two real desktop bugs were fixed along the way, both worth confirming:
- `cik-api.spec` had empty `hiddenimports`, so the packaged app shipped with
  **no PDF support at all** (the parsers are imported lazily, so PyInstaller
  could not see them). **Check: upload a PDF in the desktop app.**
- The sidecar now picks a free port instead of assuming 8000, so a clash no
  longer gives you a white screen.

Desktop logs: `~/.local/share/com.careerintelligence.kit/api.log`.

---

## 4. Adding a new field later

One YAML file, no Python — `CONTRIBUTING.md` has a fully worked example
including **how to point a new field at the right job boards**, which is the
half that actually decides result quality.

## 5. What to capture if something breaks

Surface (web/CLI/desktop), exact steps, expected vs actual, any error text,
and whether the proxy was up. Backend errors: the uvicorn terminal. Frontend:
DevTools console + network. Desktop:
`~/.local/share/com.careerintelligence.kit/api.log`.

## 6. Known and expected (not bugs)

- Cloudflare-guarded boards (FindAPhD, AAS) may be skipped on some proxy exit
  IPs — that is the polite anti-block behaviour, no CAPTCHA solving. Switching
  V2Ray server usually fixes it.
- A field with no dedicated board of its own says so in the log and still
  works via the general boards with its own keywords.
- Master's and Scholarships are deliberately disabled — one YAML flag away.
