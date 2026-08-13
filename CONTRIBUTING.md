# Contributing

Thanks for helping! The engine's design goal is **one self-contained function
per source, one YAML file per field** — adding either is a small, single-file
change that never requires touching the pipeline. Please keep that contract.

- Code lives in `phd_aggregator/` (Python engine + FastAPI) and `dashboard/`
  (Next.js). See [ARCHITECTURE.md](ARCHITECTURE.md) for the map.
- **Never bundle a refactor and a behaviour change in one commit.** Keep commits
  small and reviewable.
- **No secrets in the repo.** Tokens come from the environment or a gitignored
  `.env`; personal data (`applicant.yaml`) and uploaded CVs (`uploads/`) are
  gitignored.

## Run the tests

Everything must stay green before and after your change:

```bash
# Python engine
cd phd_aggregator
python phd_aggregator.py --self-test      # offline pipeline self-test
CIK_TESTING=1 pytest -q                    # full suite (offline fixtures)

# Dashboard
cd dashboard
npm test && npx tsc --noEmit
```

If you add pipeline behaviour, add a check to the self-test and a pytest for it.

---

## Worked example 1 — add a field profile (no Python)

A field profile is pure data — copy the template and edit it:

```bash
cd phd_aggregator
cp fields/template.yaml fields/marine_biology.yaml
```

Fill in the tiers (the template is fully commented):

```yaml
name: marine_biology
description: Marine biology and oceanographic life sciences
core_anchors:            # a post MUST match >= 1 of these to qualify at all
  - marine biolog
  - coral reef
  - oceanograph
context_terms:           # boost the score, never qualify a post alone
  - larval
  - benthic
  - remote sensing
negative_terms:          # neighbouring fields that share vocabulary
  - astrophysic
  - organic chemistry
search_terms:            # typed into each job board's own search box
  - marine biology
  - coral reef ecology
weights: { core_title: 5.0, core_desc: 2.5, context_title: 1.0, context_desc: 0.5, negative: -2.0 }
threshold: 2.0
# subfields:             # optional, for --find-supervisors --field <subfield>
```

Then verify against real listings and tune only after looking at runs:

```bash
python phd_aggregator.py --field marine_biology --limit-per-source 30 --debug
```

`--debug` logs every keep/drop decision. Or scaffold interactively with
`python phd_aggregator.py --new-field marine_biology`. The dashboard's field
dropdown picks it up automatically (it scans `fields/`).

---

## Worked example 2 — add a job-board source (one function)

Sources are plain functions registered with `@register_source`, in
`phd_aggregator/sources/<name>.py`. They receive the config and a polite HTTP
client (proxy, robots.txt, throttling, retries, anti-bot fallbacks all built
in) and return **raw** records — the pipeline does all filtering/scoring/dedup.
Fetching is concurrent, so a source must not rely on global state.

```python
# phd_aggregator/sources/eso.py
@register_source("eso")
def source_eso(cfg: Config, http: Http) -> list[dict]:
    """[FEED] ESO recruitment portal — official RSS at /jobs.rss."""
    feed = http.get_feed("https://recruitment.eso.org/jobs.rss")
    if not feed or not getattr(feed, "entries", None):
        log.warning("[eso] RSS empty/unreachable")
        return []
    out = []
    for e in feed.entries:
        out.append(make_record(
            title=e.get("title"),
            institution="European Southern Observatory",
            country=guess_country(e.get("summary")) or "Germany",
            url=e.get("link"),
            posted_date=e.get("published_parsed") or e.get("published"),
            short_description=e.get("summary"),
            source="eso",
        ))
    return out
```

Checklist:

1. Pick the *simplest* working access path, in order: official RSS/API
   (`http.get_feed`) → server-rendered HTML (`http.get_soup`) → JS rendering
   (`http.get_rendered(url, wait_selector=...)`) → full chain
   (`http.fetch_page`). Never use Playwright's `networkidle`.
2. Build records only via `make_record(...)`. Ad text → `short_description`
   (scored); location strings → `raw_location` (country detection only). Set
   `position_type="phd"` only when the source *guarantees* the level.
3. Wrap per-item parsing in `try/except`, log at `debug`, and return `[]` after
   one `log.warning` on total failure — a broken source must never crash a run.
4. Register the toggle in `SOURCES_ENABLED` (code) **and** `sources_enabled:`
   (`config.yaml`).
5. Keep drifting URLs/selectors in clearly marked constants with a
   "verified &lt;date&gt;" note.
6. Test: `python phd_aggregator.py --source eso --debug`.

The engine's fuller extension contract (seed adapters, anti-bot chain details)
lives in [phd_aggregator/CONTRIBUTING.md](phd_aggregator/CONTRIBUTING.md).

---

## Ground rules

- **Politeness is non-negotiable:** keep robots.txt handling, throttling and
  retry/backoff intact. No CAPTCHA solving, no ban evasion, no login-walled
  scraping. If a site can't be accessed politely, skip it and log why.
- **All network traffic goes through the configured proxy** — including any
  headless browser and ADS/arXiv/OpenAlex calls.
- **Preserve working behaviour.** Anything that returns real results today must
  still work after your change.
- **The self-test and both test suites must pass.**
</content>
