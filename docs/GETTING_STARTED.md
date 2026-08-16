# Getting Started

The Career Intelligence Kit aggregates open PhD/postdoc positions, matches them
against a research profile you describe, and serves the results through a REST
API and a Next.js dashboard. This guide gets you from an empty machine to seeing
your first matches.

---

## 1. Prerequisites

- **Python 3.10+** (3.11 recommended) and **pip**
- **Docker + Docker Compose** (optional, for the all-in-one stack)
- **Node.js 20.9+** (only if you run the dashboard outside Docker)
- **API keys** — all optional, features degrade gracefully if missing:

  | Key | What enables it |
  |-----|-----------------|
  | `ADS_API_TOKEN` | NASA ADS literature source for `--find-supervisors` |
  | `OPENALEX_MAILTO` | Polite-pool rate limits on OpenAlex |
  | `OPENAI_API_KEY` / `OLLAMA_HOST` | LLM profile extraction (`profile/build`) |
  | `SENTRY_DSN` | Error tracking (optional) |

---

## 2. Quick start (Docker)

The fastest path starts the API and dashboard together:

```bash
git clone <your-repo> && cd career_intelligence_kit
cp .env.example .env                 # then edit .env

# Optional: enable Redis-backed caching + background jobs + PostgreSQL
#   docker compose --profile redis --profile postgres up -d
docker compose up -d --build
```

- API: http://localhost:8000  (interactive docs at `/docs`)
- Dashboard: http://localhost:3000

The API health probe is at http://localhost:8000/health.

### First-time setup in the dashboard

1. Open http://localhost:3000 and **Create account**.
   - If the backend enforces private-beta invites (`INVITES_REQUIRED=1`), ask an
     admin for a code and paste it in the *Invite code (beta)* field.
2. Land on the **dashboard** — run the onboarding wizard at
   http://localhost:3000/onboarding, or build a profile manually.
3. On **Profile**, paste your CV/bio and press **Re-build from CV** to extract a
   structured profile.
4. Back on the dashboard, confirm your **matches** — each scored against your
   profile. Use the 👍/👎 buttons to record relevance feedback.

> Profiles are optional for the CLI but required for scoring and matches.

---

## 3. Manual setup (no Docker)

### 3.1 Backend (API + crawler)

```bash
cd phd_aggregator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# The FastAPI app reads env from the process, so source the gitignored root
# `.env` before starting (sets CORS_ORIGINS, DATABASE_URL, LLM keys, …).
set -a; source ../.env; set +a

# Run the API
uvicorn api.app:app --reload

# (optional) initialize the DB schema / apply Alembic migrations
alembic upgrade head
```

LLM features (profile build, match explanations, assistant drafting) walk a
provider chain from highest capacity down, set via `LLM_MODEL_CHAIN`
(comma-separated) in `.env`:

| Lane | Provider | Env required |
|------|----------|-------------|
| 1 | Gemini `gemini-2.5-flash-lite` | `GEMINI_API_KEY` |
| 2 | Mistral `mistral-large-latest` | `MISTRAL_API_KEY` |
| 3 | OpenAI `gpt-4o-mini` | `OPENAI_API_KEY` |

Each non-final lane is tried `LLM_CHAIN_RETRIES`+1 times before the next
lane. A blocked or out-of-credits lane fails over automatically.

### 3.2 Dashboard

```bash
cd dashboard
npm install
export NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev        # http://localhost:3000
```

---

## 4. Bootstrapping the first admin

Invite management is admin-only. Bootstrap one admin from the CLI:

```bash
cd phd_aggregator
python phd_aggregator.py --db sqlite:///phd_data.db --make-admin you@example.com
```

Then log in as that user and visit http://localhost:3000/admin to create invite
codes.

---

## 5. CLI usage (alternative to the dashboard)

The monolith-style CLI covers the crawler, profile engine and supervisor finder
without the API:

```bash
python phd_aggregator.py --self-test          # offline smoke test
python phd_aggregator.py                      # full aggregation run
python phd_aggregator.py --list-sources       # registered sources
python phd_aggregator.py --list-fields        # installed field profiles
python phd_aggregator.py --field astronomy --country Germany
python phd_aggregator.py --seed-db phd_positions.json          # load results into the DB
python phd_aggregator.py --build-profile "<your CV text>"      # LLM profile extraction
python phd_aggregator.py --show-profile                         # print the active profile
python phd_aggregator.py --find-supervisors --field astronomy --country Germany
python phd_aggregator.py --make-admin you@example.com          # promote a user to admin
```

Add `--db <DATABASE_URL>` to any DB-touching command to point at a non-default
database (e.g. PostgreSQL).

---

## 6. Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | `sqlite:///phd_data.db` | SQLAlchemy URL (SQLite or PostgreSQL) |
| `CIK_SECRET_KEY` | *(dev, insecure)* | JWT signing key — **set in production** |
| `CORS_ORIGINS` | `*` (dev) | Comma-separated allowed origins |
| `REDIS_URL` | *(unset → in-memory)* | Redis for cache + rq job queue |
| `INVITES_REQUIRED` | *(unset → optional)* | `1`/`true` = registration needs an invite |
| `SENTRY_DSN` | *(unset → off)* | Sentry error tracking DSN |
| `LLM_DEFAULT_MODEL` / `LLM_FALLBACK_MODEL` | litellm defaults | Model ids for extraction |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Dashboard's base URL to the API |

See [docs/DEPLOYMENT.md](DEPLOYMENT.md) for the full reference.

---

## 7. Tests

```bash
# Backend (all 516+ tests)
cd phd_aggregator && python -m pytest

# Dashboard
cd dashboard && npm test
```

## 8. Self-test gate (Sprint 07, Track C1)

CI and deploy hooks should run one of the repo-root scripts — they exit
non-zero on any failure:

```bash
scripts/self_test_fast.sh   # offline self-test + backend tests + dashboard tests (no network)
scripts/self_test.sh        # same, plus a warn-only live source sweep
scripts/smoke_test.sh       # post-deploy: health/ready/dashboard + register→login→profile→matches
```

---

## 9. What next?

- [API reference](API.md) — every endpoint with examples
- [Deployment guide](DEPLOYMENT.md) — Docker, PostgreSQL, Redis, SSL