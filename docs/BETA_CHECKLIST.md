# Beta Go/No-Go checklist

Tick every item before opening the private beta to users. Each item is either
built (code in the repo) or a verification step you run on the provisioned VPS.
Do not open invites while any required item is unchecked.

> **Local-dev beta (2026-08-11):** the stack runs bare-metal on the developer
> device (uvicorn :8000 + `next dev` :3000, see `command.md`). Release gates
> are checked above; deploy/ops items below apply to the VPS beta and are not
> yet ticked. This local instance uses **open registration** (`INVITES_REQUIRED`
> unset) by choice; set `INVITES_REQUIRED=1` before opening the VPS beta.

## Release gates (local, in the repo)

- [x] `scripts/self_test.sh` exits 0 on the release commit — **verified 2026-08-11 (local beta)**
- [x] `pytest tests/ -q` green (treatment: ≥660 tests at the Sprint 10 baseline) — **675 passed 2026-08-11**
- [x] `npm test -- --runInBand` green (≥66 tests) — **66 passed 2026-08-11**
- [x] `npm run lint` green and `npx tsc --noEmit` clean — **both exit 0, 2026-08-11**
- [x] `next build` compiles green — **2026-08-11**
- [ ] `pip-audit -r phd_aggregator/requirements.txt` reports 0 vulnerabilities
- [ ] `npm audit --audit-level=high` reports 0 vulnerabilities

## Deploy (on the VPS, per `docs/PROVISIONING.md`)

- [ ] Fresh `CIK_SECRET_KEY` in `.env` (never the example value)
- [ ] `.env` on the box matches `.env.example` shape (no extra/missing vars)
- [ ] `CORS_ORIGINS` = the real dashboard origin; `NEXT_PUBLIC_API_URL` = https API origin
- [ ] `API_DOMAIN`/`DASHBOARD_DOMAIN` point at the real hosts
- [ ] Firewall: only 22/80/443 open (`ufw status`)
- [ ] `docker compose ... config` validated before `up`
- [ ] `curl -sf https://api.../health` and `/ready` return 200 over HTTPS
- [ ] `curl -sf https://app.../landing` returns the landing page
- [ ] HSTS header present (`curl -sI https://api... | grep -i strict-transport`)
- [ ] Auth cookie is `Secure` + `SameSite=Strict` (full login over HTTPS in a browser)

## Security (built + verify)

- [ ] SSRF guard shipped and covered by tests (`CIK_SSRF_GUARD=1` in `.env`)
- [ ] Dependency scans clean (see above)
- [ ] `docs/SECURITY.md` checklist walked end-to-end; known gaps accepted + documented
- [ ] Reset the admin password after first login; operators use strong passwords

## Data / GDPR (built + verify)

- [ ] `/privacy`, `/terms`, `/about`, `/landing` render on the public host
- [ ] Cookie banner shows and remembers consent (functional-only cookies)
- [ ] Logged-in user can `GET /api/account/data-export` and receives JSON
- [ ] `PUT /api/account/consent` updates and persists
- [ ] `DELETE /api/account` erases PII and anonymizes analytics; user then gets 401
- [ ] These endpoints are reachable through the browser session (CSRF cookie flow)

## Ops (built + verify)

- [ ] Nightly backup ran at least once on the VPS; log shows `backup complete`
- [ ] A **restore drill succeeded in the last 7 days** (scratch DB, row counts checked)
- [ ] Backups are encrypted (`age`) — no `.dump.age` contains plaintext
- [ ] Sentry DSN live + **a test error actually fired an alert** (force one, e.g.
      hit a route with a broken input and watch Sentry)
- [ ] Uptime checks configured on `/health` + `/ready` (external monitor)
- [ ] JSON logs enabled (`CIK_JSON_LOGS=1`); a request carries `x-request-id` end-to-end
- [ ] Cron line installed for backups

## Beta access

- [ ] `INVITES_REQUIRED=1` in `.env`
- [ ] At least one invite code minted and tested (register a throwaway account with it)
- [ ] `--make-admin` run for the operator
- [ ] LLM providers (Groq/Gemini) have keys set and a match/reason call succeeded

## Sign-off

- [ ] All required items above are checked
- [ ] Known non-required gaps (load-testing at scale, WAF, DNS-pinning SSRF) are
      recorded in `docs/SECURITY.md` / `docs/MONITORING.md`
- [ ] Date opened + operator name:

```
Opened for beta on: ____________   Operator: ____________
```

Anything unchecked that is a required item → do not open invites yet. Fix,
verify, repeat.