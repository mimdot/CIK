<div align="center">

<img src="dashboard/src-tauri/icons/astra/128x128.png" width="88" alt="Astra">

# Astra

**Your academic constellation**

[![Release](https://img.shields.io/github/v/release/mimdot/CIK?label=download&color=ec3013)](https://github.com/mimdot/CIK/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-201e1d.svg)](LICENSE)
[![CI](https://github.com/mimdot/CIK/actions/workflows/ci.yml/badge.svg)](https://github.com/mimdot/CIK/actions/workflows/ci.yml)

Astra finds academic positions and supervisors — PhD openings, postdocs, funded
programmes and the people running them — and keeps the search on your own machine.

</div>

---

## Download

**[⬇ Get the latest release](https://github.com/mimdot/CIK/releases/latest)**

Every published release keeps its files permanently, so an older link never
stops working: **[v1.0.1](https://github.com/mimdot/CIK/releases/tag/v1.0.1)**
(current) · [v1.0.0](https://github.com/mimdot/CIK/releases/tag/v1.0.0) ·
[all releases](https://github.com/mimdot/CIK/releases). What changed in each is
in the [changelog](CHANGELOG.md).

### Which surface can I run?

| | Linux | macOS | Windows |
|---|---|---|---|
| **Astra CLI** (`astra`) | ✅ | ✅ | ✅ |
| **Astra Dashboard** (local web) | ✅ | ✅ | ✅ |
| **Astra Desktop** (installer) | ✅ tested on Ubuntu | ⚠️ builds, untested | ✅ built and run on Windows 11 |

The **CLI and the local dashboard run anywhere Python 3.12+ does** — they are
pure Python plus a Next.js frontend, with nothing platform-specific in them.
(3.12 is a floor, not a preference: the engine uses PEP 701 f-strings, which
are a `SyntaxError` on 3.11.)

The **desktop app** is built for all three platforms by CI from the same
source. Linux (Ubuntu) and Windows 11 have both been built and run; macOS has
not — its installer is produced and published, but nobody has yet opened one.

Two caveats on Windows, so the tick above is not read as more than it is. The
build was made and run **from source** (`.\run.ps1`); the packaged `.msi` /
setup `.exe` that CI publishes has not itself been installed. And v1.0.0's
Windows support, though written, had plainly never been executed — bringing it
up found four faults that only a real run could surface, including a `run.ps1`
that could not detect Python at all and a backend that kept running after the
app was closed. See the changelog. If you try a build, please
[open an issue](https://github.com/mimdot/CIK/issues) — good or bad.

### Desktop installers

| Your system | File to download |
|---|---|
| **Linux** — any | `.AppImage` &nbsp;→&nbsp; `chmod +x` then run |
| **Debian / Ubuntu** | `.deb` |
| **Fedora / RHEL** | `.rpm` |
| **macOS** — Apple Silicon | `…aarch64.dmg` |
| **macOS** — Intel | `…x64.dmg` |
| **Windows 10/11** | `.exe` installer (or `.msi`) |

No separate install is needed: the whole search engine and its Python runtime
are bundled, which is why the download is 150–300 MB. It works offline.

On first launch, sign in with your email and the access code you were given.

<details>
<summary><b>Windows says "Windows protected your PC"</b></summary>

Astra is not code-signed (a certificate costs a few hundred dollars a year).
Click **More info → Run anyway**. The installer is built in the open by
[this workflow](.github/workflows/tauri-release.yml) straight from the tagged
source, so you can check exactly what produced it.
</details>

<details>
<summary><b>No installer for my platform? Run the CLI or the dashboard instead</b></summary>

Both work everywhere and need no packaging:

```bash
git clone https://github.com/mimdot/CIK.git && cd CIK
cd astra && pip install -r requirements.txt
python astra.py --help
```

See [Running each surface](#running-each-surface).
</details>

---

## What it does

Academic openings are scattered across faculty pages, mailing lists and PDF
calls. Astra collects them, matches them to your field and stage, and shows you
who supervises what — so the search becomes a shortlist you can act on.

- **Positions** from academic job boards, deduplicated and freshness-filtered
- **Supervisors** ranked by an explainable 0–100 fit, from NASA ADS / OpenAlex / arXiv
- **Scored against your field**, using an editable per-field keyword taxonomy
- **Saved items** that survive a re-crawl, with notes and an application status
- **Runs anywhere**: a command, a local dashboard, or a desktop app
- **Yours alone** — see [PRIVACY.md](PRIVACY.md)

| Surface | What it is |
|---|---|
| **Astra CLI** | `astra` — the aggregator and supervisor finder |
| **Astra Dashboard** | the local web app |
| **Astra Desktop** | the packaged app (Tauri + bundled API) |

> Built to run from restricted networks: **all** traffic (requests, browser-TLS
> fallback, headless browser, ADS/arXiv/OpenAlex) routes through one configured
> proxy, with polite rate limiting and robots.txt handling. No CAPTCHA solving,
> no ban evasion — a blocked source is skipped and logged.

---

## Build it yourself (v1.0.1)

```bash
git clone https://github.com/mimdot/CIK.git && cd CIK
./run.sh
```

On Windows, same idea, PowerShell instead:

```powershell
git clone https://github.com/mimdot/CIK.git
cd CIK
.\run.ps1
```

Prerequisites, the Windows-specific parts of the build, and troubleshooting
are in **[docs/WINDOWS.md](docs/WINDOWS.md)**.

That is the whole thing — it builds whatever is missing and launches. See
[Running each surface](#running-each-surface) for the individual pieces, and
[ARCHITECTURE.md](ARCHITECTURE.md) for the full map.

| | |
|---|---|
| Changes per release | [CHANGELOG.md](CHANGELOG.md) |
| How your data is handled | [PRIVACY.md](PRIVACY.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Licence | [MIT](LICENSE) |

---

## Running each surface

### Three ways to run it

| | What it is | Start |
|---|---|---|
| **CLI** | The aggregator + supervisor finder, writes CSV/JSON/HTML | `python astra/astra.py` |
| **Local web** | Next.js dashboard + FastAPI backend | `uvicorn api.app:app` + `npm run dev` |
| **Desktop** | Tauri app bundling the dashboard + a FastAPI sidecar | `./run.sh` — or `.\run.ps1` on Windows (repo root) |

All three share the same Python engine (`astra/` package). The web and
desktop apps talk to the backend over HTTP (localhost).

---

## Install

**Python engine** (3.12+):

```bash
cd astra
pip install -r requirements.txt
# optional but recommended for JS-heavy boards:
playwright install chromium
```

Hard deps are `requests beautifulsoup4 feedparser`; everything else degrades
gracefully (see `requirements.txt`, extras are marked). The API/web stack
additionally uses `fastapi uvicorn sqlalchemy` (also in requirements).

Building the **desktop app** does not need most of that. `astra-api.spec`
excludes Playwright, LiteLLM, pandas and psycopg2 from the bundle, and a
single-user local install never reaches Redis or the RQ worker queue — so
installing the full list first downloads ~400 MB that is then discarded:

```bash
pip install -r requirements-desktop.txt   # what the bundled app actually imports
```

**Dashboard** (Node 20+):

```bash
cd dashboard
npm install
```

**Config / secrets:** copy `.env.example` to `.env` and fill in what you need.
Secrets never live in the repo — they come from the environment or the
gitignored `.env`.

---

## Running each surface

### CLI

```bash
cd astra
python astra.py                       # full run (config.yaml + defaults)
python astra.py --field biology       # switch field at runtime
python astra.py --list-fields         # installed field profiles
python astra.py --new-field marine_biology   # scaffold your own field
python astra.py --find-supervisors --field astronomy --country Germany
python astra.py --self-test           # offline pipeline test (no network)
```

Outputs are written next to `output_path` (`astra_positions.csv/.json` + a
self-contained `astra_positions.html` dashboard). Fetching is **concurrent** by
default; set `ASTRA_SOURCE_CONCURRENCY=1` to force the old sequential behaviour.

### Local web (dashboard + API)

```bash
# terminal 1 — backend
cd astra
uvicorn api.app:app --reload            # OpenAPI docs at http://localhost:8000/docs

# terminal 2 — frontend
cd dashboard
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Or the whole stack (API + Postgres + Redis + Caddy) with Docker:

```bash
docker compose up            # dev
docker compose -f docker-compose.prod.yml up   # hardened prod
```

### Desktop (Tauri)

The desktop app ships the dashboard as a static export plus a PyInstaller
**`astra-api`** sidecar (the FastAPI backend) that it launches on
`127.0.0.1:8000`.

```bash
./run.sh                     # from the repo root — builds what is missing, then starts
```

That is the whole thing. It builds the sidecar, the dashboard export and the
Tauri shell only when they are out of date (so the second run starts in well
under a second), and installs an **Astra** menu entry — after the
first run you can launch it with one click instead.

```bash
./run.sh --rebuild           # force a full rebuild first
./run.sh --no-launch         # build + install the menu entry, don't start
```

**On Windows** use `run.ps1`, which does the same job with the same switches
and installs a Start Menu shortcut instead of a `.desktop` entry:

```powershell
.\run.ps1
.\run.ps1 -Rebuild
.\run.ps1 -NoLaunch
```

Read [docs/WINDOWS.md](docs/WINDOWS.md) first — Windows needs Python 3.12+, the
MSVC Rust toolchain and the C++ build tools, and that page also explains the
three places the build is deliberately different there.

A build leaves several GB of regenerable output behind. `./scripts/clean.sh`
(or `.\scripts\clean.ps1`) frees it; `--dry-run` / `-DryRun` shows what it
would take first, and neither touches your database, profile or exports.

For development and for distributable installers, the Tauri CLI is still there:

```bash
cd dashboard
npm run tauri:dev            # dev, with hot reload
npm run tauri:build          # bundle .AppImage / .deb / .dmg / .msi
```

---

## Signing in: the shared access code

The desktop build asks for an **email and a shared access code** (default
`1819`) instead of a password. It sits *in front of* the normal account
system, which is unchanged: a real account is created on first sight, so
profiles, bookmarks and everything else work exactly as before. No password is
chosen, and none is stored.

### It is not security, and nothing here pretends otherwise

**The code ships inside a binary you hand to people.** `strings` recovers it in
seconds, and it will end up posted somewhere public. It is a front door that
asks for something rather than nothing — that is all it is for.

So: do not put data, paid features, or any real trust boundary behind it. If
you need one, that is what accounts and invite codes are for.

### Changing it, and switching back to passwords

`ASTRA_ACCESS_CODE` controls the whole thing, read at request time so no rebuild
is needed:

| `ASTRA_ACCESS_CODE` | Sign-in | `POST /api/auth/access` |
|---|---|---|
| set (desktop default `1819`) | email + code | available |
| unset or empty | email + password | **404** |

The frontend asks `GET /api/auth/config` which mode to render, so the same
build serves both — when you get a server, leave `ASTRA_ACCESS_CODE` unset there
and it presents the ordinary password form with no code change.

---

## Proxy setup (restricted networks / Iran / V2RayN)

The engine routes everything through one proxy, configured in
`astra/config.yaml`:

```yaml
proxy: "socks5h://127.0.0.1:10808"   # V2RayN SOCKS inbound (remote DNS)
proxy_fallback_direct: true          # if the proxy is dead, try direct
auto_detect_proxy: true              # else sweep common local ports
request_delay: 2.0                   # polite seconds between requests (per source)
robots_obey: true
```

- The HTTP-inbound variant is `http://127.0.0.1:10809`.
- If V2Ray runs in system-wide TUN mode the SOCKS port may be closed; the engine
  detects that and continues direct (traffic still exits the tunnel).
- The proxy fixes geo-blocks, not anti-bot walls. For Cloudflare-guarded pages
  the fetch chain is: plain requests → curl_cffi (browser TLS) → headless
  Chromium → (only if a display is present) a visible window. If a site still
  refuses, it is **skipped with a clear log line**.

Override per run with `--proxy socks5h://…` or disable with `--proxy ""`.

---

## NASA ADS token (supervisor search)

Supervisor ranking uses NASA **ADS** for astronomy/physics and **OpenAlex** for
every other field, with an **arXiv** fallback.

- **OpenAlex needs no token** and covers any field — the default for non-astro
  work. Set `OPENALEX_MAILTO` in `.env` for the polite (faster) pool.
- **ADS** improves astronomy/physics results. Get a free token at
  <https://ui.adsabs.harvard.edu/user/settings/token> and set it in `.env`:

  ```
  ADS_API_TOKEN=your-token-here
  ```

Without an ADS token the search automatically falls back to OpenAlex — it never
errors out; the dashboard's search dialog says so and links to the token page.

---

## Field profiles

A field profile (`astra/fields/<name>.yaml`) is the editable knowledge
for a subject: `core_anchors` / `context_terms` / `negative_terms` /
`search_terms` / `weights` / `threshold` (+ optional `subfields`, `departments`,
supervisor settings). 11 profiles ship (astronomy, physics, biology, chemistry,
computer_science, economics, engineering, geology, geophysics_hydro,
condensed_matter, mathematics) plus a fully-commented `template.yaml`.

- **CLI:** `--field <name>` (or `--new-field <name>` to scaffold one).
- **Web/desktop:** pick your field at the top of **Opportunities**, then
  narrow by subfield. The selection drives everything downstream.

### The field decides which boards are searched

Each source declares the disciplines it serves, so a run only visits boards
that are relevant:

| You select | Boards crawled |
|---|---|
| astronomy | the general boards **+ AAS Job Register, ESO, ESA** |
| chemistry | the general boards; `aas`/`eso`/`esa` skipped, and logged as such |
| physics / engineering | the general boards **+ ESA** |

The general boards (EURAXESS, jobs.ac.uk, FindAPhD, Nature Careers,
AcademicTransfer, AcademicJobsOnline, JREC-IN, LinkedIn, your seed URLs) are
queried with **your field's own keywords** — EURAXESS gets your research-field
facet, AcademicJobsOnline your category, LinkedIn your search phrases. A field
with no dedicated board of its own says so in the log and still works.

### The slow one is opt-in

The university **department sweep** visits every department in your field's
list at a polite 2-second delay — ~150 pages for astronomy (about five minutes
of delays alone), ~20 for most fields. It is **off by default**. Turn it on
with the checkbox on Opportunities, or `--include-slow-sources`. There is also
an instant alternative: browse the department list yourself and open any of
them directly (`GET /api/fields/<name>/departments`).

Adding a profile is a single YAML file, no Python — see
**[CONTRIBUTING.md](CONTRIBUTING.md)** for a fully worked example including how
to point a new field at the right boards.

---

## CV → profile (privacy)

Paste your CV or a short bio on the **Profile** page; the backend extracts a
structured profile (research interests, methods, tools, skills, target roles,
countries) that you can **edit before it is used**, then scores every
opportunity against it with an explanation of what matched.

**Privacy:** CV parsing stays local by default and is never sent to a
third-party service without explicit opt-in. Uploaded files are gitignored
(`astra/uploads/`) and never committed.

> Note: today the profile builder takes **pasted text**. Robust PDF/DOCX **file
> upload** is planned.

---

## Development & tests

```bash
# Python engine
cd astra
python astra.py --self-test          # offline pipeline self-test
ASTRA_TESTING=1 pytest -q                        # full suite (offline fixtures)

# Dashboard
cd dashboard
npm test                                       # jest
npx tsc --noEmit                               # typecheck
```

Contributions welcome — adding a source or a field profile is a small,
documented, single-file change. See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

---

## More docs

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — entry points, package map, data flow.
- **[astra/README.md](astra/README.md)** — deep CLI reference.
- **[astra/CONTRIBUTING.md](astra/CONTRIBUTING.md)** — the
  engine's extension contract (sources, seed adapters).
- `docs/` — the original design docs (project overview, PRD, roadmap).
</content>
