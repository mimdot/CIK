#!/usr/bin/env bash
# Career Intelligence Kit — nightly backup (Sprint 10, B2).
#
#   pg_dump -Fc  ->  encrypt with age  ->  push to object store / local dir  ->  prune
#
# Environment (see docs/BACKUPS.md):
#   DATABASE_URL          SQLAlchemy URL (postgresql://... or sqlite:///...). Falls
#                         back to $PGDUMP_URL when set (raw pg_dump target).
#   PGDUMP_URL            Optional raw postgres URL to pg_dump (else parsed from
#                         DATABASE_URL).
#   BACKUP_OBJECT_STORE    e.g. s3://bucket/backups or a local absolute dir.
#   BACKUP_DIR             Local staging/target dir when no object store. Default /var/backups/cik.
#   BACKUP_AGE_PUBLIC_KEY  age recipient public key. Unset -> plain .dump (warning).
#   BACKUP_RETENTION_DAYS  Keep at least N days of backups. Default 14.
#   BACKUP_TMP_DIR         Scratch space for the encrypted file. Default ${BACKUP_DIR}/.tmp.
#
# Intended to run from cron on the VPS host (see docs/BACKUPS.md), e.g.:
#   20 2 * * *  /opt/cik/career_intelligence_kit/scripts/backup.sh >> /var/log/cik-backup.log 2>&1
#
# Exit codes: 0 ok, 1 fatal (no backup produced), 2 degraded (backup produced but a
# non-fatal step failed, e.g. upload after local copy).

set -uo pipefail

DATABASE_URL="${DATABASE_URL:-}"
PGDUMP_URL="${PGDUMP_URL:-}"
OBJECT_STORE="${BACKUP_OBJECT_STORE:-}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/cik}"
TMP_DIR="${BACKUP_TMP_DIR:-${BACKUP_DIR}/.tmp}"
AGE_KEY="${BACKUP_AGE_PUBLIC_KEY:-}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "FATAL: $*"; exit 1; }

[ -d "${BACKUP_DIR}" ] || mkdir -p "${BACKUP_DIR}"
[ -d "${TMP_DIR}" ] || mkdir -p "${TMP_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="${BACKUP_DIR}/cik-${STAMP}"

# --- 1. produce the dump -------------------------------------------------------
DUMP=""
if [ -n "${PGDUMP_URL}" ]; then
    DUMP="${TMP_DIR}/cik-pg.dump"
    pg_dump -Fc --no-owner "${PGDUMP_URL}" -f "${DUMP}" \
        || die "pg_dump failed against PGDUMP_URL"
elif [ -n "${DATABASE_URL}" ] && [[ "${DATABASE_URL}" == postgresql* ]]; then
    DUMP="${TMP_DIR}/cik-pg.dump"
    pg_dump -Fc --no-owner "${DATABASE_URL}" -f "${DUMP}" \
        || die "pg_dump failed against DATABASE_URL"
elif [ -n "${DATABASE_URL}" ] && [[ "${DATABASE_URL}" == sqlite* ]]; then
    DBPATH="${DATABASE_URL#sqlite:///}"
    [ -f "${DBPATH}" ] || DBPATH="${DATABASE_URL#sqlite://}"
    [ -f "${DBPATH}" ] || die "sqlite file not found: ${DBPATH}"
    sqlite3 "${DBPATH}" ".backup '${TMP_DIR}/cik-sqlite.db'" >/dev/null 2>&1 \
        || cp "${DBPATH}" "${TMP_DIR}/cik-sqlite.db"
    DUMP="${TMP_DIR}/cik-sqlite.db"
else
    die "no database source (set DATABASE_URL or PGDUMP_URL)"
fi

[ -s "${DUMP}" ] || die "dump is empty (${DUMP})"

# --- 2. encrypt ---------------------------------------------------------------
ENC="${TMP_DIR}/cik-${STAMP}.dump.age"
if [ -n "${AGE_KEY}" ]; then
    if ! command -v age >/dev/null 2>&1; then
        die "BACKUP_AGE_PUBLIC_KEY set but 'age' binary not installed"
    fi
    age -r "${AGE_KEY}" -o "${ENC}" "${DUMP}" || die "age encryption failed"
    rm -f "${DUMP}"
    log "encrypted ${STAMP} with age"
else
    ENC="${DUMP}"
    log "WARNING: BACKUP_AGE_PUBLIC_KEY unset — storing UNENCRYPTED backup"
fi

# --- 3. ship it ---------------------------------------------------------------
DEST="${BASE}.dump.age"
if [ -n "${OBJECT_STORE}" ]; then
    if [[ "${OBJECT_STORE}" == s3://* ]]; then
        command -v aws >/dev/null 2>&1 || \
            die "BACKUP_OBJECT_STORE is s3:// but 'aws' CLI not installed"
        aws s3 cp "${ENC}" "${OBJECT_STORE%/}/$(basename "${DEST}")" \
            >/dev/null || { log "ERROR: s3 upload failed"; DEGRADED=1; }
    else
        mkdir -p "${OBJECT_STORE}"
        cp "${ENC}" "${OBJECT_STORE%/}/$(basename "${DEST}")" || { log "ERROR: copy to object store failed"; DEGRADED=1; }
    fi
else
    cp "${ENC}" "${DEST}" || { log "ERROR: local copy failed"; DEGRADED=1; }
fi

# --- 4. prune ----------------------------------------------------------------
PRUNE_BEFORE="$(date -u -d "-${RETENTION_DAYS} days" +%Y%m%dT%H%M%SZ 2>/dev/null \
                || date -u -v-${RETENTION_DAYS}d +%Y%m%dT%H%M%SZ 2>/dev/null \
                || printf '')"
if [ -n "${PRUNE_BEFORE}" ]; then
    for old in "${BACKUP_DIR}"/cik-*.dump.age; do
        [ -e "${old}" ] || continue
        TS="${old##*/cik-}"; TS="${TS%.dump.age}"
        if [[ "${TS}" < "${PRUNE_BEFORE}" ]]; then
            rm -f "${old}" && log "pruned ${old}"
        fi
    done
fi

rm -rf "${TMP_DIR}"
[ "${DEGRADED:-0}" = "1" ] && { log "backup DEGRADED (upload failed; local copy kept)"; exit 2; }
log "backup complete: ${DEST}"
exit 0
