# Contributing

The core design goal: **one self-contained function per source, one YAML file
per field**. A source that breaks logs a warning and is skipped — it must
never crash the run. Please keep that contract.

## Add a field profile (no Python)

1. `cp fields/template.yaml fields/<yourfield>.yaml` — the template is fully
   commented (matching rules, tier semantics, subfields).
2. Fill in `core_anchors` (unambiguous field words), `context_terms`
   (methods/instruments that only boost), `negative_terms` (neighbouring
   fields that share vocabulary), `search_terms` (what gets typed into job
   boards' search boxes) and `subfields` (for the supervisor finder).
3. Run `python phd_aggregator.py --field <yourfield> --limit-per-source 30`
   and inspect what gets kept/dropped (`--debug` logs every filter decision).
4. Tune `threshold`/`weights` only after looking at real runs.

PRs adding well-tested profiles for new fields are very welcome.

## Add a job-board source (one worked example)

Sources are plain functions registered with `@register_source`. They receive
the config and a polite HTTP client (proxy, robots.txt, throttling, retries,
anti-bot fallbacks all built in) and return **raw** records — the pipeline
does all filtering/scoring/dedup centrally.

Here is a complete, real example — an RSS feed source:

```python
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

1. Pick the *simplest* working access path, in this order:
   official RSS/API (`http.get_feed`) → server-rendered HTML
   (`http.get_soup`) → JS rendering (`http.get_rendered(url,
   wait_selector=...)`) → full chain (`http.fetch_page`). Never use
   Playwright's `networkidle` — ad-heavy boards never reach it.
2. Build records only via `make_record(...)`. Put the ad text in
   `short_description` (it is scored), department/location strings in
   `raw_location` (country detection only). Pass `position_type="phd"` only
   when the source *guarantees* the level (e.g. a PhD-only facet).
3. Wrap per-item parsing in `try/except` and log at `debug`; return `[]` on
   total failure after one `log.warning`.
4. Register the toggle: add your name to `SOURCES_ENABLED` in the code
   *and* to `sources_enabled:` in `config.yaml`.
5. Endpoint URLs and CSS selectors drift — keep them in clearly marked
   constants at the top of your function with a "verified <date>" note.
6. Test: `python phd_aggregator.py --source my_board --debug`.

## Add a seed adapter (sibling discovery for a specific board)

When the generic parent-listing heuristic can't find "other positions on the
same board" for your seed URLs, register an adapter keyed by bare domain
(no `www.`). It returns the board's listing page(s) and a regex that matches
posting paths:

```python
@seed_adapter("academicjobsonline.org")
def _adapt_academicjobsonline(seed_url: str) -> dict:
    """AJO postings live at /ajo/jobs/<id>; the astronomy listing pages
    enumerate them."""
    return {
        "listings": ["https://academicjobsonline.org/ajo/physics/Astronomy"],
        "link_re": re.compile(r"^/ajo/jobs/\d+/?$"),
    }
```

That's the whole interface: `{"listings": [urls], "link_re": pattern-on-path}`.
The seed source fetches the listing(s), collects same-domain links whose path
matches `link_re`, caps them at `seed_max_siblings`, parses each one with the
JSON-LD → meta → main-text chain, and sends them through the NORMAL filters.
The log line `domain X has appeared N times — consider a seed adapter` tells
you when writing one is worth it.

## Ground rules

* **Politeness is non-negotiable**: keep robots.txt handling, throttling and
  the retry/backoff logic intact. No CAPTCHA solving, no ban evasion, no
  login-walled scraping. If a site can't be accessed politely, skip it and
  log why.
* **No secrets in the repo**: tokens come from the environment or a
  gitignored `.env`; personal data lives in gitignored `applicant.yaml`.
* **Self-test must pass**: `python phd_aggregator.py --self-test` before and
  after your change. If you add pipeline behavior, add a check for it there.
* Defensive parsing everywhere — every field may be missing.
