# HANDOFF — audit/repair/optimize pass (2026-08-13)

Progress report + **how to test the app** so you can report what to fix next.
Branch **`chore/audit-repair`** → **PR: https://github.com/mimdot/CIK/pull/1**
(all work committed & pushed). Companion docs: `ARCHITECTURE.md`, `ISSUES.md`
(§E has the per-item progress log).

## 1. What was done (all verified & committed)

| Area | Change |
|---|---|
| Audit | `ARCHITECTURE.md` + `ISSUES.md` (reconciled the brief vs. the real tree) |
| Hygiene | untracked `phd_data.db*` + generated `phd_positions.*`; gitignored the 330 MB sidecar binary, Tauri `target/`/`gen/`, build artifacts, HTTP cache |
| **Field → run (2A)** | the selected field profile now actually drives the crawl/scoring (was always astronomy); new "Field to crawl" selector |
| **Concurrency (P1)** | sources fetched in parallel, one isolated `Http` each; **~4.3×**; `CIK_SOURCE_CONCURRENCY` (=1 = old sequential) |
| **HTTP cache (M2)** | persistent conditional-GET (ETag/Last-Modified → 304) for incremental repeat crawls; `--force-refresh` / `--no-http-cache` |
| **CV upload (2B)** | `POST /api/profile/extract-cv` → local `core/cv.py` (TXT now; PDF/DOCX need libs); Profile-page upload |
| **Streaming progress (M3)** | per-source progress in the run dialog ("N / total sources", per-source records/errors) |
| **Supervisor polish (2C)** | multi-country search, CSV/JSON export, ADS-token hint |
| **Lifespan (L3)** | migrated deprecated `@app.on_event` to a lifespan handler |
| **Sidecar robustness (L1/L2)** | free-port pick + inject base URL; `CIK_PROXY` env + config discovery; **fixed a pre-existing Rust compile error** so the desktop shell builds |
| Docs | rewrote root `README.md`, added `CONTRIBUTING.md` |

**Verification:** backend `pytest` **726 passed / 1 skipped**, dashboard `jest`
**97 passed / 15 suites**, `cargo check` clean, `tsc` clean, offline
`--self-test` green.

**Open (only item left):** CLI lazy-import startup trim (low value — the desktop
sidecar already avoids eager `pandas`).

---

## 2. How to test — do this first: the LIVE WEB app

Fastest to run and covers everything except the desktop shell.

### 2.1 One-time setup
```bash
# Python backend deps
cd phd_aggregator
pip install -r requirements.txt
pip install pdfplumber python-docx      # ONLY needed for PDF/DOCX CV upload (TXT works without)

# Dashboard deps
cd ../dashboard
npm install
```
Make sure your **V2RayN proxy is running** (SOCKS `127.0.0.1:10808`) — the real
crawl and supervisor search go through it (set in `phd_aggregator/config.yaml`,
or export `CIK_PROXY=socks5h://127.0.0.1:10808`).
Optional: put `ADS_API_TOKEN=...` and `OPENALEX_MAILTO=you@example.com` in
`phd_aggregator/.env` for better astronomy/physics supervisor results.

### 2.2 Start it (two terminals)
```bash
# Terminal 1 — backend (DB auto-creates; these envs make local dev work)
cd phd_aggregator
CIK_COOKIE_SECURE=0 CORS_ORIGINS=http://localhost:3000 uvicorn api.app:app --reload --port 8000
#   -> API + docs at http://localhost:8000/docs

# Terminal 2 — dashboard
cd dashboard
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
#   -> open http://localhost:3000
```
> `CORS_ORIGINS=http://localhost:3000` is **required** — the dashboard sends
> credentialed requests, so without it every API call fails with a CORS error.

### 2.3 Click-through checklist (in order)
1. **Register** (no invite needed by default). Password rule: ≥8 chars, one
   upper, one lower, one digit. Then **log in**.
2. **Profile** (`/profile`): (a) paste CV text → "Re-build from CV"; (b) or
   **Upload CV** (TXT always; PDF/DOCX after the pip installs). Confirm the
   extracted fields appear and are **editable**, then save.
3. **Opportunities** (`/opportunities`): choose **"Field to crawl"** (e.g.
   *biology*) → **Run engine**. Watch the dialog stream **"N / total sources"**
   and each source's record count (or red *error*). When done, cards appear.
4. **Matches** (home `/`): opportunities scored against your profile, each with a
   "why it matched" explanation. Switch the **Field** filter.
5. **Supervisors** (`/supervisors`): type a **country** (or several,
   comma-separated) + field → **Run online search** → watch progress → ranked
   results. Test **Export CSV** / **Export JSON**.
6. **Re-run** the engine (step 3) once more — the second crawl reuses the HTTP
   cache (304s), so it should be quicker.

---

## 3. How to test — the CLI (no auth; best for isolating backend issues)
```bash
cd phd_aggregator
python phd_aggregator.py --self-test                 # offline, must print ALL PASSED
python phd_aggregator.py --list-fields               # field profiles
python phd_aggregator.py --field biology --limit-per-source 5     # real crawl (needs proxy)
python phd_aggregator.py --field biology --limit-per-source 5 --force-refresh
python phd_aggregator.py --find-supervisors --field astronomy --country Germany
```
Outputs land next to the command: `phd_positions.csv/json` and a self-contained
`phd_positions.html` (open it in a browser).

---

## 4. How to test — the DESKTOP app (Tauri) — heaviest, do last
Needs a Rust toolchain + system libs (see `TAURI_BUILD_COMMANDS.txt`) and the
**sidecar binary must be built** (PyInstaller, `phd_aggregator/cik-api.spec`)
and placed at `dashboard/src-tauri/sidecar/api/cik-api-<target-triple>`.
```bash
cd dashboard
npm run tauri:dev        # dev run   (or: npm run tauri:build for installers)
```
The Rust shell now compiles (I fixed a build error) and auto-picks a free port.
Desktop logs: the sidecar writes to `<app-data>/api.log`
(Linux: `~/.local/share/com.careerintelligence.kit/api.log`).

---

## 5. What to capture when something breaks
For each issue, note: **(a)** surface (web / CLI / desktop), **(b)** exact steps,
**(c)** expected vs. actual, **(d)** any error text, **(e)** was the proxy up?
Where the errors show:
- **Web backend:** the uvicorn terminal (crawl logs, per-source errors, tracebacks).
- **Web frontend:** browser DevTools → Console + Network tabs (CORS/API errors).
- **Desktop:** `<app-data>/api.log` + the Tauri window's devtools.

## 6. Things already known / expected (not bugs)
- Some sources are Cloudflare-guarded (e.g. FindAPhD, AAS) and may be **skipped
  with an error** on certain proxy exit IPs — that's the polite anti-block
  behavior; switching V2Ray servers often helps.
- PDF/DOCX CV upload needs `pip install pdfplumber python-docx`; TXT works without.
- The desktop app needs the sidecar binary rebuilt (it's intentionally not in git).
- Pages I didn't deeply touch (admin, keys, bookmarks, settings, onboarding) are
  test-covered but not exhaustively hand-tested — likely where rough edges hide,
  so give those extra attention and report anything odd.
</content>
