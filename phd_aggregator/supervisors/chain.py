"""supervisors.chain — --find-supervisors driver (migration Step 9).
Extracted verbatim from phd_aggregator.py.

Owns the source-selection chain (ADS for astronomy/physics, OpenAlex for
every other major, arXiv as tokenless fallback), the ORCID public-email
lookup, the supervisor dashboard template, and the CLI entry point.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from core.config import (ADS_TOKEN_ENV, SUPERVISOR_ORCID_EMAILS,
                         SUPERVISOR_SENIOR_WEIGHT, Config, _find_config_path)
from core.utils import canonical_country
from supervisors.ads import ads_supervisor_docs
from supervisors.aggregate import aggregate_supervisors
from supervisors.arxiv import arxiv_supervisor_docs
from supervisors.openalex import openalex_supervisor_authors, \
    openalex_supervisor_docs

log = logging.getLogger("phd_aggregator")


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a gitignored .env (CWD or script dir) into
    os.environ — already-set variables win. No python-dotenv dependency."""
    path = _find_config_path(".env")
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = val
        log.debug("loaded environment from %s", path)
    except Exception as exc:
        log.debug(".env load failed: %s", exc)


def _supervisor_focus(cfg: Config) -> tuple[str, list[str], list[str]]:
    """(label, keywords, topics) for the requested --field: a subfield of the
    active profile, or the whole profile's search terms. `topics` are the
    OpenAlex topic IDs for the author-direct supervisor search (a subfield may
    refine them; unmapped subfields inherit the whole-major list)."""
    if cfg.subfield:
        sub = cfg.subfields.get(cfg.subfield) or {}
        kws = [str(k) for k in (sub.get("keywords") or []) if str(k)]
        label = cfg.subfield
        kws = kws or [cfg.subfield]
        topics = [str(t) for t in (sub.get("topics") or []) if str(t)]
        return label, kws, topics or list(cfg.supervisor_topics)
    return cfg.field_profile, list(cfg.search_terms), list(cfg.supervisor_topics)


def _orcid_public_email(http, orcid: str) -> Optional[str]:
    """The researcher's OWN public ORCID email record, if they published one.
    Public API, no token; anything non-public simply isn't returned."""
    from urllib.parse import quote
    url = f"https://pub.orcid.org/v3.0/{quote(orcid)}/email"
    resp = http.raw_get(url, headers={"Accept": "application/json"})
    if resp is None or resp.status_code != 200:
        return None
    try:
        emails = (resp.json() or {}).get("email") or []
        for e in emails:
            if e.get("email"):
                return e["email"]
    except Exception:
        pass
    return None


_SUPERVISOR_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Supervisor candidates — __LABEL__ / __COUNTRY__</title>
<style>
  :root {
    --bg: #f4f6fb; --card: #ffffff; --ink: #16213a; --muted: #61708b;
    --accent: #4353ff; --accent-soft: #eceeff; --ok: #0d8a4f; --warn: #c7761b;
    --bad: #c02942; --chip: #eef1f7; --border: #e3e8f2;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { background: linear-gradient(120deg, #1b2440, #31418f);
           color: #fff; padding: 26px 28px 20px; }
  header h1 { margin: 0 0 4px; font-size: 22px; }
  header .sub { color: #b9c4ea; font-size: 13px; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
              padding: 14px 28px; background: var(--card);
              border-bottom: 1px solid var(--border); position: sticky; top: 0;
              z-index: 5; }
  .controls label { font-size: 12px; color: var(--muted); display: block;
                    margin-bottom: 2px; }
  .controls select, .controls input[type=search] {
    padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px;
    background: #fff; font-size: 14px; color: var(--ink); min-width: 140px; }
  .controls input[type=search] { min-width: 200px; }
  #count { margin-left: auto; font-size: 13px; color: var(--muted); }
  main { padding: 20px 28px 60px; display: grid; gap: 14px;
         grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }
  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: 12px; padding: 16px 16px 13px; display: flex;
          flex-direction: column; gap: 8px; position: relative;
          box-shadow: 0 1px 2px rgba(20,30,70,.05); }
  .card h2 { margin: 0; font-size: 15.5px; line-height: 1.35;
             padding-right: 42px; }
  .card h2 a { color: var(--ink); text-decoration: none; }
  .card h2 a:hover { color: var(--accent); }
  .ranknum { position: absolute; top: 14px; right: 14px; color: var(--muted);
             font-size: 12px; font-weight: 700; }
  .meta { font-size: 13px; color: var(--muted); }
  .rowline { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .chip { background: var(--chip); color: #45526e; border-radius: 999px;
          padding: 2px 9px; font-size: 11.5px; text-decoration: none; }
  .chip.anchor { background: var(--accent-soft); color: var(--accent); }
  a.chip.link { background: #e8f4ee; color: var(--ok); }
  a.chip.mail { background: #fdf0e4; color: var(--warn); }
  a.chip:hover { filter: brightness(.95); }
  .score { font-weight: 700; color: var(--accent); font-size: 12.5px; }
  .papers { margin: 0; padding-left: 18px; font-size: 12.5px; color: #3c4a66; }
  .papers li { margin: 2px 0; }
  .papers a { color: #3c4a66; }
  .papers a:hover { color: var(--accent); }
  .papers .year { color: var(--muted); }
  footer { text-align: center; color: var(--muted); font-size: 12px;
           padding: 12px; }
  @media (max-width: 640px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>PhD supervisor candidates — __LABEL__ / __COUNTRY__</h1>
  <div class="sub">Generated __GENERATED__ &middot; __TOTAL__ candidates &middot;
    __SOURCE__ &middot; all data local (no network calls)</div>
</header>
<div class="controls">
  <div><label>Search</label>
    <input type="search" id="q"
           placeholder="name, topic, university, country&hellip;"></div>
  <div><label>University / institute</label>
    <input type="search" id="uni" placeholder="e.g. Bonn, MPIfR&hellip;"></div>
  <div><label>Country</label><select id="country"><option value="">All</option></select></div>
  <div><label>Topic</label><select id="topic"><option value="">All</option></select></div>
  <div><label>Contact</label>
    <select id="contact"><option value="">All</option>
      <option value="email">Public email</option>
      <option value="orcid">Has ORCID</option></select></div>
  <div><label>Sort by</label>
    <select id="sort">
      <option value="score">Score</option>
      <option value="papers">Papers</option>
      <option value="senior">Last-author papers</option>
      <option value="name">Name (A&ndash;Z)</option>
    </select></div>
  <span id="count"></span>
</div>
<main id="cards"></main>
<footer>phd_aggregator.py --find-supervisors &middot; score = +1 per matched
  paper + senior bonus when last author (usually the PI) &middot; emails only
  from public ORCID records</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById('data').textContent);
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function fill(sel, values) {
    [...new Set(values.filter(Boolean))].sort().forEach(v => {
      const o = document.createElement('option');
      o.value = v; o.textContent = v; sel.appendChild(o);
    });
  }
  fill($('country'), DATA.map(r => r.country));
  fill($('topic'), DATA.flatMap(r => (r.topics || '').split(/;\s*/)));

  function papersOf(r) {
    const seen = new Set();
    return (r.representative_papers || '').split(/\s\|\s/)
      .map(p => p.match(/^(.*?)\s*\((\d{4})\)\s*(https?:\/\/\S+)?\s*$/))
      .filter(Boolean)
      .filter(m => !seen.has(m[1]) && seen.add(m[1]))
      .map(m => ({ title: m[1], year: m[2], url: m[3] || '' }));
  }

  function render() {
    const q = $('q').value.trim().toLowerCase();
    const u = $('uni').value.trim().toLowerCase();
    const c = $('country').value, t = $('topic').value, k = $('contact').value;
    let rows = DATA.filter(r =>
      (!c || r.country === c) &&
      (!t || (r.topics || '').split(/;\s*/).includes(t)) &&
      (!k || (k === 'email' ? r.public_email : r.orcid)) &&
      (!u || (r.institution || '').toLowerCase().includes(u)) &&
      (!q || [r.name, r.institution, r.country, r.topics,
              r.representative_papers, r.public_email]
        .join(' ').toLowerCase().includes(q)));

    const mode = $('sort').value;
    rows = rows.slice().sort((a, b) => {
      if (mode === 'papers')  return (b.papers || 0) - (a.papers || 0);
      if (mode === 'senior')
        return (b.last_author_papers || 0) - (a.last_author_papers || 0);
      if (mode === 'name') return String(a.name).localeCompare(String(b.name));
      return (b.score || 0) - (a.score || 0);
    });

    $('count').textContent = rows.length + ' / ' + DATA.length + ' candidates';
    $('cards').innerHTML = rows.map(r => {
      const topics = (r.topics || '').split(/;\s*/).filter(Boolean)
        .map(x => '<span class="chip anchor">' + esc(x) + '</span>').join('');
      const papers = papersOf(r).map(p =>
        '<li>' + (p.url
          ? '<a href="' + esc(p.url) + '" target="_blank" '
            + 'rel="noopener noreferrer">' + esc(p.title) + '</a>'
          : esc(p.title))
        + ' <span class="year">(' + esc(p.year) + ')</span></li>').join('');
      return '<div class="card">'
        + '<span class="ranknum">#' + (r.rank || '?') + '</span>'
        + '<h2><a href="' + esc(r.author_search || '#') + '" target="_blank" '
        + 'rel="noopener noreferrer">' + esc(r.name) + '</a></h2>'
        + '<div class="meta">' + esc(r.institution || 'affiliation n/a')
        + ' &middot; ' + esc(r.country || 'unverified') + '</div>'
        + '<div class="rowline">'
        + '<span class="score">★ ' + (r.score || 0) + '</span>'
        + '<span class="chip">' + (r.papers || 0) + ' papers</span>'
        + '<span class="chip">' + (r.last_author_papers || 0)
        + '&times; last author</span>'
        + (r.orcid_link ? '<a class="chip link" href="' + esc(r.orcid_link)
           + '" target="_blank" rel="noopener noreferrer">ORCID</a>' : '')
        + (r.public_email ? '<a class="chip mail" href="mailto:'
           + esc(r.public_email) + '">' + esc(r.public_email) + '</a>' : '')
        + '</div>'
        + (topics ? '<div class="rowline">' + topics + '</div>' : '')
        + (papers ? '<ul class="papers">' + papers + '</ul>' : '')
        + '</div>';
    }).join('') || '<p style="color:#61708b">No candidates match the filters.</p>';
  }

  ['q', 'uni', 'country', 'topic', 'contact', 'sort'].forEach(id =>
    $(id).addEventListener('input', render));
  render();
})();
</script>
</body>
</html>
"""


def write_supervisors_html(rows: list[dict], path: str, label: str,
                           country: str, source_note: str) -> None:
    """Self-contained interactive dashboard for the ranked supervisor list:
    free-text search plus dedicated university/country/topic filters."""
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
    doc = (_SUPERVISOR_HTML_TEMPLATE
           .replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M"))
           .replace("__TOTAL__", str(len(rows)))
           .replace("__LABEL__", esc(label))
           .replace("__COUNTRY__", esc(country))
           .replace("__SOURCE__", esc(source_note))
           .replace("__DATA__", payload))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


def _supervisor_chain(cfg: Config, token: bool) -> list[str]:
    """Ordered list of literature sources to try for --find-supervisors, in
    preference order. `auto` picks ADS for astronomy/physics (it indexes them
    best and needs a token) and OpenAlex for every other major."""
    requested = (cfg.supervisor_source or "auto").strip().lower()
    if requested == "arxiv":
        return ["arxiv"]
    if requested == "ads":
        return (["ads", "openalex"] if token else ["openalex", "arxiv"])
    if requested == "openalex":
        return ["openalex"]
    # auto: astronomy/physics -> ADS first; everything else -> OpenAlex
    if token and cfg.supervisor_ads_db in ("astronomy", "physics"):
        return ["ads", "openalex"]
    return ["openalex", "arxiv"]


SOURCE_LABELS = {
    "ads": "NASA ADS",
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
}
AUTHOR_SEARCH_FMT = {
    # {name} is URL-encoded when the row is built (aggregate_supervisors)
    "ads": 'https://ui.adsabs.harvard.edu/search/q=author:"{name}"',
    "openalex": "https://openalex.org/search/authors?q={name}",
    "arxiv": 'http://export.arxiv.org/api/query?search_query=au:"{name}"',
}


def find_supervisors(cfg: Config, http) -> int:
    """--find-supervisors driver: query OpenAlex / ADS / arXiv (in the order
    the active field profile selects), aggregate + rank, write
    supervisors_<field>_<country>.csv/.json/.html, print the top of the list.

    ADS only indexes astronomy + physics; OpenAlex (no token) covers EVERY
    major, so e.g. --field economics --country Germany now works out of the
    box."""
    import pandas as pd

    if not cfg.geo_filter_active or not cfg.countries:
        log.error("--find-supervisors needs --country <name> "
                  "(e.g. --country Germany)")
        return 2
    country = cfg.countries[0]
    if len(cfg.countries) > 1:
        log.info("[supervisors] multiple countries given — using %r "
                 "(run once per country)", country)
    label, keywords, focus_topics = _supervisor_focus(cfg)
    log.info("[supervisors] field=%s country=%s keywords=%s "
             "(last %d years)%s", label, country, keywords,
             cfg.supervisor_years_back,
             f" topics={focus_topics}" if focus_topics else "")

    token = bool(os.environ.get(ADS_TOKEN_ENV))
    chain = _supervisor_chain(cfg, token)
    log.info("[supervisors] literature sources: %s",
             " -> ".join(SOURCE_LABELS.get(s, s) for s in chain))
    if not token and "ads" in chain:
        log.warning("[supervisors] no %s in the environment — using %s "
                    "instead (no token needed). Get a free ADS token at "
                    "https://ui.adsabs.harvard.edu/user/settings/token",
                    ADS_TOKEN_ENV, SOURCE_LABELS.get(
                        next(s for s in chain if s != "ads"), "OpenAlex"))

    # ADS and OpenAlex can verify each author's affiliation themselves (ADS via
    # free-text guess, OpenAlex via structured per-author country codes); arXiv
    # affiliations are too sparse, so we aggregate without a per-author filter
    # and normalize the country afterwards.
    # For the PAPER-aggregation path the per-profile seniority signal decides
    # the authorship-position bonus: economics/finance order alphabetically
    # (supervisor_senior_signal: none -> no last-author bonus); astronomy/
    # physics and biology-style fields keep it.
    senior_weight = (SUPERVISOR_SENIOR_WEIGHT
                     if cfg.supervisor_senior_signal == "last_author" else 0.0)

    ranked: list[dict] = []
    used_source: Optional[str] = None
    for src in chain:
        if src == "ads":
            if not token:
                continue
            docs = ads_supervisor_docs(cfg, http, os.environ[ADS_TOKEN_ENV],
                                       keywords, country)
            ranked = aggregate_supervisors(
                docs, country if docs else None, keywords,
                min_papers=cfg.supervisor_min_papers,
                senior_weight=senior_weight,
                search_fmt=AUTHOR_SEARCH_FMT["ads"]) if docs else []
        elif src == "openalex":
            if focus_topics or cfg.supervisor_field:
                # Author path: real researchers via curated OpenAlex topics (or
                # the profile's OpenAlex field when no topics are curated) +
                # country, ranked by h-index and recent activity.
                ranked = openalex_supervisor_authors(
                    cfg, http, focus_topics, country, cfg.supervisor_field)
            if not ranked:
                # Fallback: keyword-matched papers (old/custom profiles with
                # neither supervisor_topics nor supervisor_field).
                docs = openalex_supervisor_docs(cfg, http, keywords, country)
                ranked = aggregate_supervisors(
                    docs, country if docs else None, keywords,
                    min_papers=cfg.supervisor_min_papers,
                    senior_weight=senior_weight,
                    search_fmt=AUTHOR_SEARCH_FMT["openalex"]) if docs else []
        else:
            docs = arxiv_supervisor_docs(cfg, http, keywords)
            ranked = aggregate_supervisors(
                docs, None, keywords,
                min_papers=cfg.supervisor_min_papers,
                senior_weight=senior_weight,
                search_fmt=AUTHOR_SEARCH_FMT["arxiv"]) if docs else []
            if ranked and country:
                target = canonical_country(country)
                ranked = [r for r in ranked
                          if r["country"] in (target, "unverified")]
        if ranked:
            used_source = src
            break
        log.warning("[supervisors] %s returned no candidates — trying the "
                    "next source", SOURCE_LABELS.get(src, src))
    if not ranked:
        log.error("[supervisors] no candidates found in any source "
                  "(%s) — cannot rank supervisors",
                  ", ".join(SOURCE_LABELS.get(s, s) for s in chain))
        return 1

    if SUPERVISOR_ORCID_EMAILS:
        looked = 0
        for r in ranked[:15]:
            if r["orcid"] and looked < 15:
                looked += 1
                email = _orcid_public_email(http, r["orcid"])
                if email:
                    r["public_email"] = email
                    r["email_source"] = "orcid_public_record"
        log.info("[supervisors] ORCID public-email lookups: %d "
                 "(only self-published contacts are used — never guessed)",
                 looked)

    from core.utils import _slugify
    stem = f"supervisors_{_slugify(label, 30)}_{_slugify(country, 30)}"
    out_dir = os.path.dirname(os.path.abspath(cfg.stem))
    csv_path = os.path.join(out_dir, stem + ".csv")
    json_path = os.path.join(out_dir, stem + ".json")
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    cols = ["rank", "name", "institution", "country", "score", "papers",
            "last_author_papers", "topics", "representative_papers",
            "author_search", "orcid", "orcid_link", "public_email",
            "email_source"]
    pd.DataFrame(ranked)[cols].to_csv(csv_path, index=False)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(ranked, fh, indent=2, ensure_ascii=False)
    html_path = os.path.join(out_dir, stem + ".html")
    if cfg.write_html:
        write_supervisors_html(
            ranked, html_path, label, canonical_country(country) or country,
            f"{SOURCE_LABELS[used_source]}, last {cfg.supervisor_years_back} "
            "years")
    log.info("[supervisors] %d ranked candidates -> %s , %s%s",
             len(ranked), csv_path, json_path,
             f" , {html_path}" if cfg.write_html else "")

    print(f"\nTop supervisor candidates — {label} / {country} "
          f"({SOURCE_LABELS[used_source]}, last "
          f"{cfg.supervisor_years_back} years):")
    for r in ranked[:15]:
        mail = f"  <{r['public_email']}>" if r.get("public_email") else ""
        print(f"  {r['rank']:>2}. {r['name']:<28} score {r['score']:>6}  "
              f"({r['papers']} papers, {r['last_author_papers']}x last "
              f"author){mail}")
        if r.get("institution"):
            print(f"      {str(r['institution'])[:90]}")
    print(f"\nFull list: {csv_path}"
          + (f"\nInteractive: {html_path} (search by name/topic/"
             "university/country)" if cfg.write_html else "")
          + "\nEmails are only filled from PUBLIC ORCID records; otherwise "
            "check the person's institutional page (linked via ORCID/author "
            "search) yourself.\n")
    return 0
