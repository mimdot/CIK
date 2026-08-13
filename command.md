# Running the Dashboard

## Option 1: Bare-metal (Recommended for the local beta on this device)

Terminal 1 — backend API on :8000. The FastAPI app reads env vars from the
process, not the file, so **source the gitignored root `.env` first**:

```bash
cd phd_aggregator
set -a; source ../.env; set +a    # CORS_ORIGINS, DATABASE_URL, LLM keys…
uvicorn api.app:app --port 8000    # add --reload for dev loops
```

Terminal 2 — dashboard on :3000:

```bash
cd dashboard
npm run dev                        # NEXT_PUBLIC_API_URL defaults to http://localhost:8000
```

Then open http://localhost:3000. Health probe: http://localhost:8000/health.

Note: the checked-in root `.env` sets `CIK_COOKIE_SECURE=0` because this device
serves the dashboard over plain HTTP (`http://localhost`) — browsers drop
`Secure` cookies on such origins, which silently breaks login sessions. Keep it
unset/`1` behind TLS. The dashboard decides "logged in" by asking
`GET /api/auth/me` (the session cookie is httpOnly), so after a reload you stay
signed in.

### First login locally

The form's primary button is **Log in**, which only works for existing
accounts. On a fresh database, click **Create account** to register (dev mode
needs no invite code), then you are auto-logged in.

### LLM provider chain (profile build / explanations / assistant)

Providers are walked in order of capacity with fast failover:

| Lane | Provider | Env require |
|------|----------|-------------|
| 1 | Gemini `gemini-2.5-flash-lite` | `GEMINI_API_KEY` |
| 2 | Mistral `mistral-large-latest` | `MISTRAL_API_KEY` |
| 3 | OpenAI `gpt-4o-mini` | `OPENAI_API_KEY` |

Set via `LLM_MODEL_CHAIN` (comma-separated) in `.env`; each non-final lane is
tried `LLM_CHAIN_RETRIES`+1 times before the next lane. If Gemini is
network-blocked from this machine, Mistral serves the calls automatically.

---

## Option 2: Direct `npm run dev` only (frontend, dev fastest path)

```bash
cd dashboard
npm run dev
```

This requires the API backend to be running separately (above or via docker).

---

## Option 3: Docker Compose (Full Stack)

```bash
# From project root
docker-compose up dashboard
```

This runs the dashboard at http://localhost:3000 with the API backend at http://localhost:8000

---

## Notes

- The dashboard requires the API backend to be running
- Environment variables are configured in `.env` and `docker-compose.yml`
- `NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000`
- First user can be promoted to admin with
  `cd phd_aggregator && source ../.env && python phd_aggregator.py --make-admin you@example.com`
