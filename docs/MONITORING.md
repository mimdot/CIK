# Monitoring

How the private-beta service is watched: Sentry for errors, uptime checks on
the health endpoints, JSON request logging, and an alert → triage runbook.

## 1. Sentry (error tracking)

Sentry is initialized when `SENTRY_DSN` is set (see `api/app.py`). The Sprint 09
work tags events, so a handful of alert rules cover everything that matters:

| Alert rule | Tags (filter) | What it means | First action |
|------------|---------------|---------------|--------------|
| UnhandledError | `level:error`, no `handled` flag | A request crashed end-to-end | Read the stack; open the matching `x-request-id` log line |
| PipelineJobFailed | `event:pipeline_job_failed` | A pipeline run ended in failure | `docker compose logs worker`; retry from Admin → Jobs |
| SourceDrift | `event:source_drift` | A source's data quality changed | Inspect `GET /api/admin/source-health` |
| AnomalyDetected | `event:anomaly_detected` | 5xx storm / latency spike | Look at `/api/admin/anomalies` + recent access logs |
| LLMAccountedFail | `event:llm_failed` | LLM call failed after retries | Restock provider keys; check `/api/admin/metrics` → llm |

Configure each rule to notify email/PagerDuty/Slack on first occurrence, with a
1/hour debounce.

## 2. Uptime checks

External monitors (UptimeRobot, Healthchecks.io, cronitor) hitting:

- `GET https://<api-domain>/health` every minute — expect 200.
- `GET https://<api-domain>/ready` every minute — expect 200 (503 means DB down).

Notify on first failure **and** on recovery. A `ready` 503 while `health` is 200
means Postgres is unreachable — check the `api` + `postgres` containers before
anything else.

## 3. JSON logs + request ids

Production runs with `CIK_JSON_LOGS=1` (`docker-compose.prod.yml`), emitting one
JSON object per line with `time`, `level`, `logger`, `message`, and `request_id`.
Every HTTP request also:

- accepts/echoes `X-Request-Id` (set your own to correlate),
- emits one `http <METHOD> <path> -> <status> (<ms>)` access line carrying the id.

This is the correlation story: a Sentry event with a broken user flow → grep the
logs for its request id across api + worker.

Example triage for a 500 reported by a user:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api \
  | grep 'status": 500' -- --after-context 0 --before-context 0 | tail -50
# or, with a known request id:
docker compose logs api | grep '<that-request-id>'
```

## 4. Alert → triage runbook (summary)

1. **Which surface?** Error from a user flow (Sentry/up time), a failed crawl
   (PipelineJobFailed), or capacity (AnomalyDetected)?
2. **Open `/api/admin/*`** — source-health, anomalies, tasks, metrics — they tell
   you drifted sources, erroring endpoints, dead letters and pool usage before
   you touch a terminal.
3. **Find the request id** of the earliest failing event and grep the logs.
4. **Fix** — usually one of: restart the failing healthcheck-less container,
   retry a pipeline job, revoke a source, or restore an API key quota.
5. **Confirm recovery** — uptime check green + `/api/admin/metrics` 5xx back to
   baseline, and note it in the beta runbook.

## 5. What is NOT monitored yet (beta gap)

- No Prometheus/Grafana dashboards (the admin `/metrics` tab is the built-in
  dashboard).
- No on-call rotation — the beta operator is the on-call. Document who that is.