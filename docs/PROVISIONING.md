# Provisioning a beta VPS

The end state: a single cheap VPS running `postgres`, `redis`, `worker`, `api`,
`dashboard`, and `caddy` under Docker Compose, behind automatic HTTPS, with a
nightly backup. You run these steps once; after that, day-to-day ops live in
`BETA_RUNBOOK.md`.

## 0. What you need

- A Linux VPS. Recommended baseline for a beta of a few dozen users: **2 vCPU,
  4 GB RAM, 40 GB SSD** (Ubuntu 22.04/24.04 LTS). Scale up 1→2 vCPU only if
  `/api/admin/metrics` shows p95 latency climbing.
- A domain (or two subdomains), e.g. `api.cik.example` + `app.cik.example`.
  Point both `A` records at the VPS IP before issuing TLS.
- This repository on the box: `git clone <your-repo> career_intelligence_kit`.

## 1. Harden the base OS

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ufw age
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
sudo adduser cik        # service account; add your key to its authorized_keys
```

Only 22/80/443 open. Add swap if the box reports low memory at startup:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
```

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker cik
sudo systemctl enable --now docker
# log the cik user out/in once so the docker group applies
```

## 3. Configure the app

```bash
cd career_intelligence_kit
cp .env.example .env
# then fill in, at minimum:
#   CIK_SECRET_KEY=(fresh)   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
#   CORS_ORIGINS=https://app.cik.example
#   NEXT_PUBLIC_API_URL=https://api.cik.example
#   API_DOMAIN=api.cik.example
#   DASHBOARD_DOMAIN=app.cik.example
#   DATABASE_URL=postgresql://cik:CHANGE_STRONG_PASSWORD@postgres:5432/cik
#   REDIS_URL=redis://redis:6379/0
#   INVITES_REQUIRED=1
#   SENTRY_DSN=https://...@sentry.io/...
#   GROQ_API_KEY=...  GEMINI_API_KEY=...   (LLM providers)
#   BACKUP_AGE_PUBLIC_KEY=age1...  (see docs/BACKUPS.md)
#   CIK_SSRF_GUARD=1
```

Generate the age key if you will encrypt backups:

```bash
age-keygen -o ~/.config/cik-backup.agekey   # keep the private file off-box
cat ~/.config/cik-backup.agekey | grep 'public key'
```

## 4. Launch the stack

```bash
docker compose --profile redis --profile postgres \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Caddy will fetch a Let's Encrypt certificate for both subdomains automatically
(the first request may 502 for a few seconds while the cert issues — that is
normal). Verify:

```bash
curl -sf https://api.cik.example/health && echo HEALTH_OK
curl -sf https://app.cik.example/landing -o /dev/null && echo DASHBOARD_OK
```

## 5. First-run: migrate, admin, seed, invites

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec api alembic upgrade head

# create your admin account (you'll use its token to mint invite codes):
docker compose ... exec api python phd_aggregator.py --make-admin you@example.com

# load seed positions if you have a curated file:
docker compose ... exec api python phd_aggregator.py --db "$DATABASE_URL" --seed-db phd_positions.json
```

## 6. Nightly backup + restore drill

Add the cron line (docs/BACKUPS.md):

```bash
sudo crontab -u root -e
# 20 2 * * *  cd /home/cik/career_intelligence_kit && BACKUP_OBJECT_STORE=/var/backups/cik ./scripts/backup.sh >> /var/log/cik-backup.log 2>&1
```

Run one backup now and do a **restore drill into a scratch DB** before inviting
anyone (docs/BACKUPS.md, section "Restore drill").

## 7. Confirm the beta checklist

Run `docs/BETA_CHECKLIST.md` top to bottom. Nothing on it should be "no".

## Rollback / teardown

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
# keep the cik-pgdata volume! That volume is the database.
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v  # only if you truly want to wipe
```