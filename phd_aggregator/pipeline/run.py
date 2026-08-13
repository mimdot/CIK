"""pipeline.run — the orchestration runner (migration Step 8). Extracted
verbatim from the original monolith.

``run`` fetches enabled sources, filters, freshness-checks, dedupes, detects
NEW entries, writes outputs and prints the summary. Also the sort/new-output
helpers and the self-contained HTML dashboard template.
"""

from __future__ import annotations

import json
import os
import re
import logging
import time
from datetime import datetime
from typing import Optional

from core.config import Config
from core.http import Http
from core.records import OUTPUT_FIELDS
from core.utils import dedupe_key
from sources.base import SOURCES, log
from pipeline.dedupe import dedupe_records
from pipeline.filter import filter_records
from pipeline.freshness import apply_freshness, load_state, save_state


# Sorting + persistence + NEW-entry detection
# -----------------------------------------------------------------------------
def sort_key(r: dict) -> tuple:
    """Relevance first (highest wins, ApplyKite-style), then soonest deadline
    (missing deadlines last), then posted date."""
    d, p = r.get("deadline"), r.get("posted_date")
    return (-(r.get("relevance_score") or 0.0),
            d is None, d or "9999-12-31",
            p is None, p or "9999-12-31")


def load_previous_keys(json_path: str) -> tuple[set, bool]:
    """Return (set_of_dedupe_keys, is_first_run)."""
    if not os.path.exists(json_path):
        return set(), True
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            prev = json.load(fh)
        return {dedupe_key(r) for r in prev}, False
    except Exception as exc:
        log.warning("could not read previous output %s: %s", json_path, exc)
        return set(), True


def mark_new(records: list[dict], prev_keys: set, first_run: bool) -> int:
    """Set is_new on each record. On the very first run there is no baseline,
    so nothing is flagged 'new'."""
    if first_run:
        for r in records:
            r["is_new"] = False
        return 0
    n = 0
    for r in records:
        new = dedupe_key(r) not in prev_keys
        r["is_new"] = new
        n += int(new)
    return n


def _record_source(name: str, raw_records: int, error: bool,
                   duration_s: float) -> None:
    """Best-effort per-source instrumentation for the source-health monitor."""
    try:
        from core.source_monitor import record_error, record_run
        if error:
            record_error(name)
        else:
            record_run(name, raw_records=raw_records, duration_s=duration_s)
    except Exception as exc:  # monitoring must never break the pipeline
        log.warning("source_monitor instrumentation failed: %s", exc)


# -----------------------------------------------------------------------------
# Outputs: CSV + JSON + self-contained HTML dashboard (Task E)
# -----------------------------------------------------------------------------
def write_outputs(records: list[dict], cfg: Config) -> None:
    import pandas as pd  # local import: only needed for CSV writing

    # Track B6/C3: when a profile was active, extend the schema with the match
    # columns. Baseline runs are byte-for-byte identical to before.
    fields = list(OUTPUT_FIELDS)
    if any("match_score" in r for r in records):
        fields += ["match_score", "match_explanation"]

    rows = []
    for r in records:
        d = {k: r.get(k) for k in fields}  # drops internal raw_location
        rows.append(d)

    # JSON (keeps list fields as lists)
    with open(cfg.json_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, ensure_ascii=False)

    # CSV (list fields joined; pandas handles quoting)
    csv_rows = []
    for d in rows:
        c = dict(d)
        for f in ("matched_keywords", "matched_anchors"):
            if isinstance(c.get(f), list):
                c[f] = "; ".join(c[f])
        csv_rows.append(c)
    pd.DataFrame(csv_rows, columns=fields).to_csv(cfg.csv_path, index=False)

    written = [cfg.csv_path, cfg.json_path]
    if cfg.write_html:
        write_html(rows, cfg)
        written.append(cfg.html_path)
    log.info("wrote %d records -> %s", len(rows), " , ".join(written))

# The dashboard is one self-contained file: data embedded as JSON, vanilla JS,
# zero external requests. Delete this block (and WRITE_HTML) if you only want
# the CSV/JSON data.
_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Astronomy PhD positions</title>
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
  .controls input[type=search] { min-width: 220px; }
  #count { margin-left: auto; font-size: 13px; color: var(--muted); }
  main { padding: 20px 28px 60px; display: grid; gap: 14px;
         grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }
  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: 12px; padding: 16px 16px 13px; display: flex;
          flex-direction: column; gap: 8px; position: relative;
          box-shadow: 0 1px 2px rgba(20,30,70,.05); }
  .card h2 { margin: 0; font-size: 15.5px; line-height: 1.35; }
  .card h2 a { color: var(--ink); text-decoration: none; }
  .card h2 a:hover { color: var(--accent); }
  .meta { font-size: 13px; color: var(--muted); }
  .desc { font-size: 13px; color: #3c4a66; }
  .rowline { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .chip { background: var(--chip); color: #45526e; border-radius: 999px;
          padding: 2px 9px; font-size: 11.5px; }
  .chip.anchor { background: var(--accent-soft); color: var(--accent); }
  .chip.src { background: #e8f4ee; color: var(--ok); }
  .badge-new { position: absolute; top: -8px; right: 12px; background: var(--bad);
               color: #fff; font-size: 10.5px; font-weight: 700;
               letter-spacing: .5px; padding: 2px 8px; border-radius: 999px; }
  .score { font-weight: 700; color: var(--accent); font-size: 12.5px; }
  .dl { font-size: 12.5px; font-weight: 600; }
  .dl.far { color: var(--ok); } .dl.soon { color: var(--warn); }
  .dl.verysoon { color: var(--bad); } .dl.none { color: var(--muted);
  font-weight: 400; }
  footer { text-align: center; color: var(--muted); font-size: 12px;
           padding: 12px; }
  @media (max-width: 640px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>Astronomy &amp; Astrophysics PhD positions</h1>
  <div class="sub">Generated __GENERATED__ &middot; __TOTAL__ positions &middot;
    sorted by relevance &middot; all data local (no network calls)</div>
</header>
<div class="controls">
  <div><label>Search</label>
    <input type="search" id="q" placeholder="title, institution, topic&hellip;"></div>
  <div><label>Sort by</label>
    <select id="sort">
      <option value="relevance">Relevance</option>
      <option value="deadline">Deadline (soonest)</option>
      <option value="posted">Newest posted</option>
      <option value="effective">Freshest (effective date)</option>
    </select></div>
  <div><label>Country</label><select id="country"><option value="">All</option></select></div>
  <div><label>Source</label><select id="source"><option value="">All</option></select></div>
  <div><label>Type</label><select id="ptype"><option value="">All</option></select></div>
  <div><label>Freshness</label><select id="fresh"><option value="">All</option></select></div>
  <div><label>&nbsp;</label>
    <select id="newonly"><option value="">All entries</option>
      <option value="new">NEW only</option></select></div>
  <span id="count"></span>
</div>
<main id="cards"></main>
<footer>phd_aggregator.py &middot; relevance = tiered astronomy taxonomy
  (core anchors &times; title weighting)</footer>
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
  fill($('source'), DATA.flatMap(r => (r.source || '').split(/;\s*/)));
  fill($('ptype'), DATA.map(r => r.position_type));
  fill($('fresh'), DATA.map(r => r.freshness));

  const today = new Date().toISOString().slice(0, 10);
  function dlInfo(r) {
    if (!r.deadline) return { cls: 'none', label: 'no deadline listed' };
    const days = Math.round((new Date(r.deadline) - new Date(today)) / 864e5);
    if (days < 0)  return { cls: 'none', label: 'closed ' + r.deadline };
    if (days <= 7)  return { cls: 'verysoon', label: r.deadline + ' · ' + days + 'd left' };
    if (days <= 30) return { cls: 'soon', label: r.deadline + ' · ' + days + 'd left' };
    return { cls: 'far', label: r.deadline + ' · ' + days + 'd left' };
  }

  function render() {
    const q = $('q').value.trim().toLowerCase();
    const c = $('country').value, s = $('source').value,
          t = $('ptype').value, n = $('newonly').value,
          f = $('fresh').value;
    let rows = DATA.filter(r =>
      (!c || r.country === c) &&
      (!s || (r.source || '').split(/;\s*/).includes(s)) &&
      (!t || r.position_type === t) &&
      (!f || r.freshness === f) &&
      (!n || r.is_new) &&
      (!q || [r.title, r.institution, r.short_description, r.country,
              (r.matched_anchors || []).join(' ')]
        .join(' ').toLowerCase().includes(q)));

    const mode = $('sort').value;
    rows.sort((a, b) => {
      if (mode === 'deadline') {
        return (a.deadline || '9999') < (b.deadline || '9999') ? -1 : 1;
      }
      if (mode === 'posted') {
        return (b.posted_date || '') < (a.posted_date || '') ? -1 : 1;
      }
      if (mode === 'effective') {
        return (b.effective_date || '') < (a.effective_date || '') ? -1 : 1;
      }
      return (b.relevance_score || 0) - (a.relevance_score || 0);
    });

    $('count').textContent = rows.length + ' / ' + DATA.length + ' positions';
    $('cards').innerHTML = rows.map(r => {
      const dl = dlInfo(r);
      const anchors = (r.matched_anchors || []).slice(0, 6)
        .map(a => '<span class="chip anchor">' + esc(a) + '</span>').join('');
      const srcs = (r.source || '').split(/;\s*/).filter(Boolean)
        .map(x => '<span class="chip src">' + esc(x) + '</span>').join('');
      return '<div class="card">'
        + (r.is_new ? '<span class="badge-new">NEW</span>' : '')
        + '<h2><a href="' + esc(r.url || '#') + '" target="_blank" '
        + 'rel="noopener noreferrer">' + esc(r.title || '(untitled)') + '</a></h2>'
        + '<div class="meta">' + esc(r.institution || 'Institution n/a')
        + ' · ' + esc(r.country || 'Unknown') + '</div>'
        + '<div class="rowline"><span class="dl ' + dl.cls + '">⏳ '
        + esc(dl.label) + '</span>'
        + '<span class="score">★ ' + (r.relevance_score || 0) + '</span>'
        + '<span class="chip">' + esc(r.position_type || '?') + '</span>'
        + (r.freshness ? '<span class="chip" title="effective date '
           + esc(r.effective_date || '?') + '">' + esc(r.freshness) + ' · '
           + (r.age_days == null ? '?' : r.age_days) + 'd</span>' : '')
        + srcs + '</div>'
        + (r.short_description
           ? '<div class="desc">' + esc(r.short_description) + '</div>' : '')
        + (anchors ? '<div class="rowline">' + anchors + '</div>' : '')
        + '</div>';
    }).join('') || '<p style="color:#61708b">No positions match the filters.</p>';
  }

  ['q', 'sort', 'country', 'source', 'ptype', 'newonly'].forEach(id =>
    $(id).addEventListener('input', render));
  render();
})();
</script>
</body>
</html>
"""


def write_html(rows: list[dict], cfg: Config) -> None:
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    html = (_HTML_TEMPLATE
            .replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__TOTAL__", str(len(rows)))
            .replace("__DATA__", payload))
    with open(cfg.html_path, "w", encoding="utf-8") as fh:
        fh.write(html)

def print_summary(records: list[dict], new_count: int, first_run: bool,
                  cfg: Config) -> None:
    def tally(field_name: str) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for r in records:
            val = r.get(field_name) or "Unknown"
            if field_name == "source":  # records may carry merged "a; b"
                for s in re.split(r";\s*", val):
                    counts[s] = counts.get(s, 0) + 1
            else:
                counts[val] = counts.get(val, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    line = "=" * 64
    print("\n" + line)
    print(f"PhD position aggregation — {datetime.now():%Y-%m-%d %H:%M}")
    print(line)
    print(f"Total positions: {len(records)}")
    if first_run:
        print("NEW since last run: (baseline run — no previous file to compare)")
    else:
        print(f"NEW since last run: {new_count}")

    print("\nBy source:")
    for name, n in tally("source"):
        print(f"  {name:<22} {n}")

    print("\nBy country:")
    for name, n in tally("country"):
        print(f"  {name:<22} {n}")

    ptypes = tally("position_type")
    if ptypes:
        print("\nBy position type:")
        for name, n in ptypes:
            print(f"  {name:<22} {n}")

    fresh = tally("freshness")
    if any(name != "Unknown" for name, _ in fresh):
        print("\nBy freshness (how the effective date was derived):")
        for name, n in fresh:
            print(f"  {name:<22} {n}")

    # relevance distribution (title anchors score 5+; desc-only 2.5+)
    buckets = {"high (>=8)": 0, "medium (4-8)": 0, "low (<4)": 0}
    for r in records:
        s = r.get("relevance_score") or 0
        if s >= 8:
            buckets["high (>=8)"] += 1
        elif s >= 4:
            buckets["medium (4-8)"] += 1
        else:
            buckets["low (<4)"] += 1
    print("\nBy relevance:")
    for name, n in buckets.items():
        print(f"  {name:<22} {n}")

    top = sorted(records, key=sort_key)[:10]
    if top:
        print("\nTop matches:")
        for r in top:
            dl = r.get("deadline") or "no deadline"
            print(f"  [{r.get('relevance_score', 0):>5}] [{dl}] "
                  f"{(r.get('title') or '(no title)')[:70]}")
            print(f"          {r.get('institution') or ''} — {r.get('country')}")

    if not first_run and new_count:
        print("\nNEW entries (up to 25):")
        shown = 0
        for r in records:
            if not r.get("is_new"):
                continue
            dl = r.get("deadline") or "no deadline"
            print(f"  [{dl}] {r.get('title') or '(no title)'}"
                  f" — {r.get('institution') or r.get('country') or ''}")
            print(f"      {r.get('url') or ''}")
            shown += 1
            if shown >= 25:
                break
    print(line + "\n")


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------
def apply_profile_matching(records: list[dict], profile, cfg: Config) -> list[dict]:
    """Score every kept opportunity against a UserProfile (Track B6/C3).

    Deterministic and offline: each record gets ``match_score`` +
    ``match_explanation``, then the list is re-sorted by match score (falling
    back to relevance_score). Mutates and returns ``records`` (adds
    match_score + match_explanation keys, re-sorts)."""
    from matching import score_match
    for opp in records:
        result = score_match(profile, opp, cfg)
        opp["match_score"] = result.overall_score
        opp["match_explanation"] = result.explanation
    records.sort(key=lambda r: -(r.get("match_score")
                                 or r.get("relevance_score", 0.0)))
    return records


def _source_concurrency() -> int:
    """How many sources to fetch in parallel. One worker == one source == one
    domain, so this caps how many DOMAINS are hit at once; it never raises the
    in-flight request count against a single domain (that stays 1, and the
    polite per-request delay is preserved per source). Override with
    ``CIK_SOURCE_CONCURRENCY`` (1 = the old fully-sequential behaviour)."""
    try:
        return max(1, int(os.environ.get("CIK_SOURCE_CONCURRENCY", "6")))
    except (TypeError, ValueError):
        return 6


def fetch_sources(cfg: Config, only_sources: Optional[list[str]] = None,
                  limit_per_source: Optional[int] = None,
                  on_progress=None) -> list[dict]:
    """Fetch every enabled source and return the concatenated raw records.

    Sources are fetched CONCURRENTLY (thread pool), each in its own isolated
    :class:`Http` (``detect=False`` — the caller must resolve the proxy once
    first by constructing an ``Http(cfg)``). Isolation means one slow, hanging
    or crashing source can neither block nor corrupt the state (throttle,
    curl_cffi rotation cursor, browser context) of another. Results are
    reassembled in the original source order, so the output is byte-for-byte
    identical to a sequential run regardless of completion order (deterministic
    dedupe/merge downstream).

    ``on_progress``, if given, is called with small dicts as the run advances so
    a UI can stream per-source status: once with ``{"event": "start", "total":
    N}`` and then, as EACH source finishes (in completion order),
    ``{"event": "source", "source", "status": "done"|"error", "records",
    "duration"}``. It may be called from worker threads, so the callback must be
    thread-safe; it is best-effort and never allowed to break a run."""
    def _is_enabled(name: str) -> bool:
        return ((name in only_sources) if only_sources
                else cfg.sources_enabled.get(name, False))

    todo: list[tuple] = []
    for name, fn in SOURCES.items():
        if _is_enabled(name):
            todo.append((name, fn))
        else:
            log.info("skip %s (disabled)", name)

    def _emit(event: dict) -> None:
        if on_progress is None:
            return
        try:
            on_progress(event)
        except Exception as exc:  # progress must never break the crawl
            log.debug("progress callback failed: %s", exc)

    _emit({"event": "start", "total": len(todo)})

    def _fetch_one(name, fn) -> list[dict]:
        t0 = time.time()
        worker_http = Http(cfg, detect=False)
        try:
            recs = fn(cfg, worker_http) or []
        except Exception as exc:  # one source failing never sinks the run
            log.warning("source %s failed (%s) — continuing", name, exc,
                        exc_info=cfg.debug)
            _record_source(name, raw_records=-1, error=True,
                           duration_s=time.time() - t0)
            _emit({"event": "source", "source": name, "status": "error",
                   "records": 0, "duration": round(time.time() - t0, 2)})
            return []
        finally:
            worker_http.close()
        for r in recs:
            r.setdefault("source", name)
        if limit_per_source:
            recs = recs[:limit_per_source]
        log.info("source %s -> %d raw records", name, len(recs))
        _record_source(name, raw_records=len(recs), error=False,
                       duration_s=time.time() - t0)
        _emit({"event": "source", "source": name, "status": "done",
               "records": len(recs), "duration": round(time.time() - t0, 2)})
        return recs

    workers = max(1, min(len(todo), _source_concurrency()))
    if workers <= 1 or len(todo) <= 1:
        raw: list[dict] = []
        for name, fn in todo:
            log.info("running source: %s", name)
            raw.extend(_fetch_one(name, fn))
        return raw

    from concurrent.futures import ThreadPoolExecutor, as_completed
    log.info("fetching %d sources concurrently (%d workers)", len(todo), workers)
    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="src") as pool:
        futures = {pool.submit(_fetch_one, name, fn): name for name, fn in todo}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()  # _fetch_one never raises
    # Reassemble in source order for a deterministic, sequential-identical list.
    raw = []
    for name, _ in todo:
        raw.extend(results.get(name, []))
    return raw


def run(cfg: Config, only_sources: Optional[list[str]] = None,
        limit_per_source: Optional[int] = None,
        injected_raw: Optional[list[dict]] = None,
        profile=None, on_progress=None) -> list[dict]:
    """Fetch enabled sources, filter, freshness-check, dedupe, detect NEW,
    write, summarise. `injected_raw` bypasses network fetching (--self-test).
    When a UserProfile is supplied (Track C3), every kept opportunity is scored
    against it (match_score + match_explanation) and the list is re-sorted by
    match score (falling back to relevance)."""
    raw: list[dict] = []
    http: Optional[Http] = None

    if injected_raw is not None:
        raw = [dict(r) for r in injected_raw]
    else:
        # The parent Http resolves the proxy ONCE (detect=True) and is reused by
        # the freshness stage below. The actual crawl runs concurrently, one
        # isolated Http per source — see fetch_sources().
        http = Http(cfg)
        try:
            raw = fetch_sources(cfg, only_sources=only_sources,
                                limit_per_source=limit_per_source,
                                on_progress=on_progress)
        finally:
            http.close()

    kept = filter_records(raw, cfg)
    state = load_state(cfg)
    kept = apply_freshness(kept, cfg, state, http=http)
    save_state(state, cfg)
    deduped = dedupe_records(kept)
    deduped.sort(key=sort_key)

    if profile:
        # Track B6/C3: score every kept opportunity against the active profile
        # (deterministic, no LLM) and re-sort by match score.
        apply_profile_matching(deduped, profile, cfg)

    prev_keys, first_run = load_previous_keys(cfg.json_path)
    new_count = mark_new(deduped, prev_keys, first_run)

    write_outputs(deduped, cfg)
    print_summary(deduped, new_count, first_run, cfg)
    return deduped
