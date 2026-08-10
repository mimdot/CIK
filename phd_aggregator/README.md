# PhD Position Aggregator

> **New here / not a programmer?** Follow the step-by-step beginner guide —
> works for any major: **[English](GETTING_STARTED.md)** ·
> **[فارسی](GETTING_STARTED.fa.md)**

A single-file, polite crawler that aggregates **open PhD positions** from a
dozen academic job boards, scores them against a tiered field taxonomy,
filters by position type / region / freshness, deduplicates across boards,
and writes `CSV + JSON + a self-contained HTML dashboard`. It ships fully
worked for **astronomy & astrophysics**, but any field is a YAML file away
(`fields/*.yaml`) — no Python edits needed.

Extras: a **supervisor finder** — for ANY major — that mines OpenAlex
(no token, all disciplines) or NASA ADS / arXiv for academics likely to
supervise a PhD in a given subfield + country, a **seed file** for
hand-picked position links (with automatic sibling discovery on the same
board), per-position **application-email drafts**, and curated
professor/scholarship shortlists.

Built to work from **restricted networks** (developed from Iran behind a
V2RayN proxy): every request — including the headless browser — goes through
one configurable proxy, with a layered anti-bot fallback chain that stays
polite (no CAPTCHA solving, no ban evasion; blocked sites are skipped with a
clear log line).

## Install

```bash
python -m pip install -r requirements.txt          # core + recommended
playwright install chromium                        # optional: JS-heavy boards
```

Only `requests / beautifulsoup4 / feedparser / pandas` are hard requirements;
everything else degrades gracefully (the log tells you what you're missing
and what it would buy you).

## Quick start

```bash
python phd_aggregator.py --self-test     # offline pipeline test (no network)
python phd_aggregator.py                 # full run -> phd_positions.{csv,json,html}
python phd_aggregator.py --list-sources  # what's registered/enabled
python phd_aggregator.py --list-fields   # installed field profiles (fields/*.yaml)
python phd_aggregator.py --country Germany --country Japan
python phd_aggregator.py --field astronomy          # explicit field profile
```

Open `phd_positions.html` in a browser: search, filter by country / source /
type / freshness, sort by relevance, deadline or effective date. Entries new
since the previous run are badged **NEW**.

## The four building blocks

### 1. Field profiles — retarget to YOUR field (`fields/*.yaml`)

All subject knowledge (core anchors, context terms, negative terms, search
terms, scoring weights, subfields) lives in `fields/astronomy.yaml`. Runtime
settings (proxy, sources on/off, countries, freshness window, seed options)
live in `config.yaml`. Both are optional overlays over built-in defaults —
delete a key and the default returns; CLI flags beat everything.

To hunt PhDs in another field:

```bash
python phd_aggregator.py --list-fields             # what's already installed
python phd_aggregator.py --new-field marine_biology  # interactive wizard
# or hand-write one:
cp fields/template.yaml fields/marine_biology.yaml   # fully commented
$EDITOR fields/marine_biology.yaml
python phd_aggregator.py --field marine_biology
```

The repo ships 10 ready-made profiles — astronomy, physics, chemistry,
biology, geology, geophysics/hydrogeology, mathematics, computer science,
economics and engineering — each with its own keywords, subfields and a
per-field registry of university department pages (`departments:` in the
YAML). A profile without a `departments:` block falls back to the built-in
worldwide university registry; `departments: []` disables that source.
Profiles whose vocabulary overlaps other fields can set
`require_title_anchor: true` (as `computer_science` does) so a post must have
a core keyword in its *title* to qualify — description matches only boost the
score, keeping e.g. ML-heavy astrophysics posts out of a CS search.

### 2. Supervisor finder

```bash
# Works for ANY major out of the box — no API token needed:
python phd_aggregator.py --find-supervisors --field economics --country Germany
python phd_aggregator.py --find-supervisors --field computer_science --country Japan
python phd_aggregator.py --find-supervisors --field biology --country United States
# Astronomy/physics (best index) with the optional ADS token:
python phd_aggregator.py --find-supervisors --field ism --country Germany
```

The literature source is picked automatically from the field profile
(`--supervisor-source auto`, `openalex` | `ads` | `arxiv` to force):

* **OpenAlex** (default for every non-astro/physics profile, no token):
  covers **all** disciplines — CS, economics, biology, chemistry, engineering,
  geology, mathematics... — with structured author affiliations and ORCIDs,
  filtered to the target country server-side.
* **NASA ADS** (default for astronomy/physics): best index for those fields;
  needs a free token (`ADS_API_TOKEN`). Ranks authors by publication
  frequency **plus a last-author bonus** (in astronomy the last author is
  usually the PI/supervisor).
* **arXiv**: tokenless fallback; affiliations best-effort, flagged
  `unverified`.

If a source returns nothing the tool automatically tries the next one. Writes
`supervisors_<field>_<country>.csv/.json/.html` with: name, institution,
country, score, matched topics, representative recent papers (with DOI/ADS
links), a per-source author-search link (OpenAlex/ADS), ORCID, and a contact
email **only** when the researcher publishes one on their public ORCID record
— emails are never guessed. The `.html` file is a self-contained interactive
dashboard (no network calls): free-text search plus dedicated
university/institute, country, topic and contact filters, sortable by score,
papers, last-author papers or name (`--no-html` skips it).

Subfields come from the active field profile (`ism`, `magnetism`,
`cosmology`, `galaxies`, `exoplanets`, `stellar`, `radio` in the astronomy
profile); `--field astronomy` uses the whole profile's search terms.

#### Getting an ADS token (free, 2 minutes; only needed for astro/physics)

1. Create an account at <https://ui.adsabs.harvard.edu>.
2. Generate a token at <https://ui.adsabs.harvard.edu/user/settings/token>.
3. `cp .env.example .env` and paste it in (`.env` is gitignored), or
   `export ADS_API_TOKEN=...`. **Never commit the token.**

### 3. Seed URLs — feed it the links it missed

Keep hand-picked position URLs in `seeds.txt` (one per line, `#` comments).
Each seed is fetched through the full anti-bot chain and parsed via
**JSON-LD JobPosting → OpenGraph/meta → readability main text**. Hand-picked
seeds bypass the relevance/type gates by default (`seed_bypass_gate` in
`config.yaml`) but are still scored, classified and deadline/freshness-
filtered. For every seed the tool also looks for the board's parent listing
page and ingests **sibling postings** — those go through the normal filters.
Domains that keep appearing in your seeds are flagged in the log as
candidates for a dedicated adapter/source (see `CONTRIBUTING.md`).

### 4. Freshness — undated posts don't live forever

Every record gets an `effective_date` derived in priority order: **future
deadline** (always kept) → **posted date** → **first-seen timestamp** (the
run that discovered the URL records it in `.seen_positions.json`) → a date
read off the page itself. Posts with no future deadline older than
`max_age_days` (default 365) are dropped as stale; a truly dateless post is
kept on first discovery and ages out naturally on later runs. The summary
prints a per-run breakdown (kept by deadline / posted / first-seen /
undated-new vs dropped stale) and the dashboard can filter/sort by it.

## Running from a restricted network (e.g. Iran)

* Default proxy: `socks5h://127.0.0.1:10808` (V2RayN SOCKS inbound; the `h`
  resolves DNS through the proxy so poisoned local DNS can't break lookups).
  The HTTP-inbound variant is `http://127.0.0.1:10809` — set it in
  `config.yaml` or `--proxy`.
* **Auto-detection (default on):** the tool verifies the configured proxy with
  a real request (a listening port is not a working proxy), and if it's dead it
  sweeps the common local ports (V2RayN, Clash, sing-box, V2rayNG...) and uses
  the first one that actually routes traffic. Whichever VPN app you run and on
  whatever port, it just works. Disable with `auto_detect_proxy: false` or
  `--no-proxy-detect`. If nothing works it probes direct connectivity and
  either continues with a clear log line or tells you to check the VPN — it
  never silently hangs.
* **TUN / system-wide mode:** the local SOCKS port may be closed; with
  `proxy_fallback_direct: true` the script detects that and continues
  without an explicit proxy (traffic still exits through the tunnel).
* All stages use the proxy: plain requests, `curl_cffi`, and Playwright
  (Chromium is launched with the proxy + remote-DNS resolver flags).
* The proxy fixes **GEO blocks**. **Anti-bot walls** (Cloudflare) are handled
  by the layered chain: realistic browser headers → browser-TLS
  fingerprint (`curl_cffi`) → headless Chrome (`domcontentloaded` +
  `wait_for_selector`, never `networkidle`) → optionally a visible browser
  window. If a site still refuses, it is **skipped politely** — no CAPTCHA
  solving, no ban evasion. Note: some VPN exit IPs have such bad reputation
  that Cloudflare refuses even a real browser (AAS/FindAPhD do this on some
  exits) — switching the V2Ray server is the fix, not code.
* The Playwright browser keeps a **persistent profile** (`.pw_profile`,
  gitignored) so cookies survive between runs — a site that trusted you
  yesterday keeps trusting you today. `--fresh-profile` wipes it if a site
  starts challenging again; `--browser-profile DIR` relocates it.
* Politeness: robots.txt honored (`robots_obey`), per-request delay,
  retries with backoff.

## All modes

| Command | What it does |
|---|---|
| `python phd_aggregator.py` | full aggregation run |
| `--self-test` | offline test of the whole pipeline (no network) |
| `--find-supervisors --field economics --country Germany` | ranked supervisor list for any major (OpenAlex, no token) |
| `--supervisor-source openalex\|ads\|arxiv` | force a literature source for the supervisor finder |
| `--field <profile-or-subfield>` | select field profile / subfield |
| `--list-fields` / `--new-field <name>` | list profiles / scaffold a new one interactively |
| `--seeds myseeds.txt` | alternate seed file |
| `--country X` (repeatable) | region filter |
| `--max-age-days N` | freshness window |
| `--source euraxess` (repeatable) | run only these sources |
| `--proxy ""` | disable the proxy |
| `--no-proxy-detect` | skip the local-port sweep (configured proxy or direct only) |
| `--no-config` | ignore config.yaml |
| `--phd-only` | strict: drop positions whose level isn't verifiable as a PhD |
| `--write-emails` | draft one application email per found position |
| `--find-professors` / `--scholarships` / `--extras` | curated shortlists |
| `--no-fetch` | reuse the previous JSON (for `--write-emails` etc.) |
| `--no-html` | skip the results dashboard (`--write-html` re-enables) |
| `--browser-profile DIR` | persistent browser profile (cookies survive runs → fewer Cloudflare challenges) |
| `--fresh-profile` | wipe the persistent browser profile before starting |
| `--challenge-wait MS` | ms to wait for an anti-bot challenge to auto-clear |
| `--limit-per-source N` / `--debug` / `--list-sources` | development aids |

## Outputs

| File | Content |
|---|---|
| `phd_positions.csv/.json` | all kept positions, sorted by relevance |
| `phd_positions.html` | self-contained dashboard (no network calls) |
| `supervisors_<field>_<country>.csv/.json` | ranked supervisor candidates |
| `supervisors_<field>_<country>.html` | interactive supervisor dashboard (search by name/topic/university/country) |
| `phd_positions_universities.csv` | department registry + fetch status |
| `emails/`, `professors.*`, `scholarships.*` | career-toolkit extras |
| `.seen_positions.json` | first/last-seen state (gitignored) |

## Personal data & secrets

`applicant.yaml` (your contact details for email drafts) and `.env` (ADS
token) are **gitignored**; copy the `*.example*` files to create them. The
repository itself contains no secrets.

## Code layout

The single `phd_aggregator.py` is being split into modules under `core/`
(migration plan: `../MIGRATION_PLAN.md` at the repo root). Step 1:

- `core/config.py` — the CONFIG block (constants), the `Config` object, the
  `config.yaml` + `fields/*.yaml` plumbing and `build_config()`. The monolith
  re-imports every name from it, so the CLI and all importers behave exactly
  as before.

## Adding sources / fields / adapters

See [CONTRIBUTING.md](CONTRIBUTING.md) — a new job-board source is typically
~15 lines with the `@register_source` decorator.

## Disclaimer

Scrapes public listings for personal job-hunting. Respect each site's terms.
The LinkedIn source uses the public guest search for a handful of throttled,
personal-use queries and overrides robots.txt for them — read its docstring
and set `linkedin: false` in `config.yaml` if you're not comfortable with
that.
