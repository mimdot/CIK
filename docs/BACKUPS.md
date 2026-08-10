# Backups

Nightly, encrypted, pruned backups with a tested restore path (Sprint 10, B2).

## What runs

`scripts/backup.sh` from a host cron (one line, no container required):

```
20 2 * * *  /opt/cik/career_intelligence_kit/scripts/backup.sh >> /var/log/cik-backup.log 2>&1
```

It follows the same shape whether the database is PostgreSQL or SQLite:

1. **Dump** — `pg_dump -Fc` for PostgreSQL, or a consistent file copy for SQLite.
2. **Encrypt** — `age -r <public key>` (age is a small static binary; install it on the VPS).
3. **Ship** — `aws s3 cp` against any S3-compatible store, a local dir, or `BACKUP_DIR`.
4. **Prune** — delete backups older than `BACKUP_RETENTION_DAYS` (default 14).

Returns exit 0 (ok), 1 (fatal — no backup produced; alert on this), or 2 (degraded —
stored locally but the upload failed).

## Configuration (.env)

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | — | SQLAlchemy URL; the script auto-detects Postgres vs SQLite |
| `PGDUMP_URL` | — | Optional raw `postgresql://` target for `pg_dump` when `DATABASE_URL` is not a PG URL |
| `BACKUP_OBJECT_STORE` | — | `s3://bucket/path` (needs `aws` CLI) or any absolute directory |
| `BACKUP_DIR` | `/var/backups/cik` | Local target / staging dir |
| `BACKUP_AGE_PUBLIC_KEY` | *(unset → plain!)* | age recipient (`age-keygen`). Do not run production without it |
| `BACKUP_RETENTION_DAYS` | `14` | Keep at least N days |
| `BACKUP_TMP_DIR` | `$BACKUP_DIR/.tmp` | Scratch space |

Generate an age key once and store the PRIVATE key far away (a separate box or a
password manager):

```bash
age-keygen -o /root/.config/cik-backup.agekey   # on the VPS
cat /root/.config/cik-backup.agekey | grep 'public key'
# put the public key line into BACKUP_AGE_PUBLIC_KEY in .env
```

## Restore drill (do this at least once before opening the beta)

1. **Find the backup** you want to restore (e.g. `cik-20260809T020000Z.dump.age`).
2. **Decrypt** locally with the private key:

   ```bash
   age -d -i /root/.config/cik-backup.agekey \
       cik-20260809T020000Z.dump.age > cik-20260809T020000Z.dump
   ```

3. **Restore into a scratch database** first (never directly over production):

   ```bash
   # SQLite
   cp cik-20260809T020000Z.dump /tmp/scratch.db

   # PostgreSQL
   createdb cik_restore_drill
   pg_restore -Fc -d cik_restore_drill cik-20260809T020000Z.dump
   ```

4. **Verify row counts** match the pre-backup admin dashboard numbers
   (`/api/admin/metrics`: users, positions, matches):

   ```bash
   psql cik_restore_drill -c "SELECT (SELECT count(*) FROM users)     AS users,
                                    (SELECT count(*) FROM opportunities) AS opps,
                                    (SELECT count(*) FROM matches)    AS matches;"
   ```

5. **Swap** only after the scratch data checks out: stop writes, restore into the
   real database, restart the API, run `scripts/smoke_test.sh`.

The drill is complete when you have restored a backup taken after real user data
existed (during the beta, do it weekly at first).

## What if a backup is needed in an emergency?

1. Quick path: `docker compose --profile postgres -f docker-compose.yml -f docker-compose.prod.yml exec postgres pg_dump -Fc cik -f /var/lib/postgresql/data/emergency.dump` — keep this inside the compose data volume while you work.
2. Then follow the restore drill above.
3. Never restore directly over the live database before verifying the scratch copy.