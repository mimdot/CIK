# Beta Runbook

Day-to-day operations for whoever runs the private beta service. Covers invites,
admin access, day-to-day health, upgrades, and incidents. Provisoning steps are
in `PROVISIONING.md`; the go/no-go list is in `BETA_CHECKLIST.md`.

All `docker compose` commands assume:

```bash
cd astra
COMPOSE="docker compose --profile redis --profile postgres \
         -f docker-compose.yml -f docker-compose.prod.yml"
```

## 1. Admins

**Make someone an admin** (they then mint invite codes and see the Admin tab):

```bash
$COMPOSE exec api python astra.py --make-admin friend@example.com
```

**Get a bearer token as an admin** (for curl, e.g. minting invites):

```bash
curl -s https://api.astra.example/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}' \
  -c cookies.txt
# token lives in the session cookie; OR use the LoginForm + devtools.
```

## 2. Invites (how users get in)

Registration is gated by `INVITES_REQUIRED=1` in production. Check status:

```bash
curl -s https://api.astra.example/api/invites -H "Authorization: Bearer $TOKEN"
```

**Mint one invite** (admin):

```bash
curl -s -X POST https://api.astra.example/api/invites \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"note":"beta-wave-1"}'
# -> {"code":"abc...","used":false,...}
```

Or use the **Admin → Invites** tab in the dashboard. Send the code privately to
each beta user; codes are single-use.

**Close the beta**: switch to an invite-less mode for a day (dev/pilot) or revoke
by leaving `INVITES_REQUIRED=1` and simply never minting more codes.

## 3. Day-to-day health (2-minute check)

```bash
curl -sf https://api.astra.example/health          # liveness
curl -sf https://api.astra.example/ready           # readiness (DB linked)
$COMPOSE ps                                       # all containers Up/healthy
```

Open the **Admin tab** on the dashboard and look at Metrics / Source health /
Anomalies — it refreshes every 30 s. Any 5xx or drifted source shows there.

## 4. Pipeline runs

Run a full crawl+score manually (worker enqueues; harmless to repeat):

```bash
curl -s -X POST https://api.astra.example/api/pipeline/run \
  -H "Authorization: Bearer $TOKEN"
```

Watch it: `$COMPOSE logs --tail 50 worker`. A failed job appears under
Admin → Jobs; you can retry it from there or via `POST /api/admin/tasks/{id}/retry`.

## 5. Backups

- Nightly script runs from root cron (see `PROVISIONING.md` step 6).
- Verify daily: `tail -5 /var/log/astra-backup.log` shows `backup complete`.
- Restore drill at least weekly during the first month (`docs/BACKUPS.md`).
- If a backup ever exits 1 (fatal), page the operator: that night has no backup.

## 6. Upgrading

```bash
git pull                       # fetch the new release tag
$COMPOSE up -d --build         # rebuild + restart
$COMPOSE exec api alembic upgrade head    # only if a migration shipped
$COMPOSE restart worker
curl -sf https://api.astra.example/health && echo UP
```

Before the upgrade, run all four gates locally (`scripts/self_test.sh`, pytest,
npm test, `next build`). Don't upgrade against a DB without a fresh backup first.

## 7. Common incidents

### 7.1 "Cannot log in / cookie lost"
Verify HTTPS: the auth cookie is `Secure` + `SameSite=Strict` and will not be
sent on plain HTTP or cross-origin. Check `CORS_ORIGINS` matches exactly.

### 7.2 Digests never arrive
- `$COMPOSE logs worker | grep -i digest` — rq-scheduler cron registered once?
  (If `API_WORKERS>1`, every extra worker must run with `ASTRA_SCHEDULER_ENABLED=0`.)
- Check `GET /api/admin/metrics` → email events; confirm the Resend domain is
  verified and low bounce rate.

### 7.3 Pipeline fails / source drift
Admin → Source health shows which source degraded. Common fix: the upstream site
changed layout → update the source adapter; or an LLM/ADS key quota expired →
renew and retry the job.

### 7.4 High latency / pool exhaustion
`GET /api/admin/pool-status` shows DB pool health. `AnomalyDetected` alerts on
latency spikes. Remedies: restart `postgres`, tune `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`
in `.env` and `$COMPOSE up -d`; check `/api/admin/metrics` for hot endpoints.

### 7.5 Someone wants their data / erasure
They do it themselves in the dashboard (Account → Export / Delete account) — or
tell them to and confirm with `GET /api/admin/audit` (`account.delete` row). This
is a GDPR right, not an incident: do it promptly.

## 8. Contact roster

Record who is on call and their contact point. For the beta this is likely the
operator who invited users. Update this section when that changes.