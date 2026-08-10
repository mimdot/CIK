# SOURCE_HEALTH.md — Source Health Audit (D3)

> Generated during **Sprint 2026** (2026-08-03), after migration Steps 2–4
> (`core/utils.py`, `core/records.py`, `core/taxonomy.py`, `core/http.py`) and
> the B1 academictransfer fix. Each enabled source was run individually with
> `--source X --limit-per-source 2..5 --proxy ""` and timed.
>
> **Interpretation:** every source ran without any `AttributeError` or crash —
> the migration did not break the source layer. `ese/eso` etc. reflect live
> endpoint behaviour on the audit date. Raw counts are the limit-capped
> *raw* records returned by the source function *before* the central
> relevance/type/geo filters.
>
> Large slow sources like `uni_departments` time-slice across many department
> sites and are inherently slow; a 3-record cap understates them.

## Enabled-source matrix

| # | Source | Type | Playwright required | Measured time | Raw records (capped) | Warnings / notes |
|---|--------|------|--------------------|---------------|----------------------|------------------|
| 1 | euraxess | FEED/HTML | No | ~19 s | 4 | none |
| 2 | nature_careers | HTML | No | ~15 s | 4 | none |
| 3 | jobs_ac_uk | HTML | No | ~11 s | 4 | none |
| 4 | academicjobsonline | HTML | No | ~14 s | 4 | none |
| 5 | jrecin | HTML | No | ~9 s | 4 | none |
| 6 | eso | FEED | No | ~4 s | 4 | none — used as the S4 live gate |
| 7 | esa | HTML | No | ~7 s | 4 | none |
| 8 | linkedin | HTML** | No (browser-TLS/robots override) | ~34 s | 3 | guest search; personal-use robots override documented |
| 9 | seed_urls | registry (parses saved URLs) | No | ~46 s | 3 | one seed URL retried after a proxy drop (`/ajo/jobs/31950`) |
| 10 | uni_departments | HTML sweep | No | >100 s (uncapped, dials many sites) | 0 *at 3-cap* | slow by design; writes `<out>_universities.csv` |
| 11 | academictransfer | JS (Playwright XHR interception) | **Yes** | ~21 s | 3 | **B1 fix** — now uses the shared persistent context; no error |
| 12 | aas | FEED/JS | **Yes** (RSS is Cloudflare-blocked) | ~85 s | 0 | RSS returned 403 → fell back to Playwright graduate-category page; browser path returned 0 listings (IP-reputation / Cloudflare) |
| 13 | findaphd | JS (Playwright) | **Yes** | ~73 s | 0 | "0 listings (Cloudflare block or selector drift)" — same known VPN-exit-IP issue |

Disabled stubs (intentionally not implemented): `iau`, `astrobetter`, `china`, `korea`, `new_zealand` — `[off] by default`.

## 2. Playwright requirement per source

- **Requires Playwright** (JS / anti-bot): `findaphd`, `academictransfer`, `aas` (fallback path).
- **Works without Playwright:** the rest. `linkedin` uses session/curl_cffi only.
- Every source still degrades gracefully: if Playwright is absent, JS sources
  log a clear warning and fall back to SSR / skip (see `core/http.py`).

## 3. Response-time observations

- The ~8–15 s floor on simple HTML/FEED sources is the polite `REQUEST_DELAY`
  (2 s) throttle × page fan-out, not endpoint slowness. In a full run these run
  in parallel across sources.
- Playwright-backed sources dominate wall-clock time (browser bootstrap +
  challenge-tolerance) — 20–90 s each.

## 4. Drift / failure modes to watch

1. **aas + findaphd**: likely Cloudflare → real browser block (IP reputation on
   the VPN exit). Working (non-zero) before presumably; documents 0 on this
   exit. Try another V2Ray server; not a code regression.
2. **uni_departments**: very slow (many sites) — keep low caps / batch it.
3. **seed_urls**: one `ProxyError`-style retry observed for a single URL —
   polite retry handled it (3 records still returned).

## 5. Last known working state

- All 13 enabled sources ran in Sprint 2026 without exceptions.
- Zero non-stub sources crashed the process.

## 6. Method note

Timings include the `--proxy ""` (direct) probe + network latency and are
subject to VPN/exit fluctuation; record counts are capped by `--limit-per-source`
so they are lower bounds, not full-fidelity counts. A baseline without a cap
(one clean full run) is the recommended next calibration.