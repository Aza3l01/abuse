#!/usr/bin/env bash
# Nightly Postgres backup: pg_dump | gzip, checked locally, then uploaded to S3.
# Config comes from the environment, or from the repo .env when run by cron:
#   DATABASE_URL       required
#   BACKUP_S3_BUCKET   required (bucket name only, for example clew-db-backups)
#   BACKUP_S3_PREFIX   optional, default db-backups
# AWS credentials come from the environment, the repo .env (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
# AWS_DEFAULT_REGION, the clew-server user) or the normal AWS CLI chain.
# Exits non-zero on any failure. Nothing is ever deleted; expiry is the bucket lifecycle rule.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

dotenv_value() {
  local file="$REPO_DIR/.env"
  [[ -f "$file" ]] || return 0
  { grep -E "^$1=" "$file" || true; } | tail -n 1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"
}

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup_postgres: $*"; }
die() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup_postgres: ERROR: $*" >&2; exit 1; }

DATABASE_URL="${DATABASE_URL:-$(dotenv_value DATABASE_URL)}"
BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-$(dotenv_value BACKUP_S3_BUCKET)}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-$(dotenv_value BACKUP_S3_PREFIX)}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-db-backups}"

[[ -n "$DATABASE_URL" ]] || die "DATABASE_URL is not set"
[[ -n "$BACKUP_S3_BUCKET" ]] || die "BACKUP_S3_BUCKET is not set"

# Cron has no AWS config, so pick up the clew-server keys from .env when they are set there.
for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION; do
  if [[ -z "${!name:-}" ]]; then
    value="$(dotenv_value "$name")"
    if [[ -n "$value" ]]; then export "$name=$value"; fi
  fi
done

# SQLAlchemy style URLs (postgresql+psycopg2://) are not valid for libpq.
DATABASE_URL="$(sed -E 's#^(postgres(ql)?)\+[A-Za-z0-9]+://#\1://#' <<<"$DATABASE_URL")"

tmp="$(mktemp "${TMPDIR:-/tmp}/clew_backup.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

key="${BACKUP_S3_PREFIX%/}/clew_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"

log "dumping database"
pg_dump --no-owner --no-privileges --dbname="$DATABASE_URL" | gzip -c > "$tmp" \
  || die "pg_dump or gzip failed"

# The server role cannot read objects back, so the dump is verified before upload.
gzip -t "$tmp" || die "gzip integrity check failed"
gzip -dc "$tmp" | tail -n 5 | grep -q "PostgreSQL database dump complete" \
  || die "dump is truncated (completion marker missing)"

size="$(wc -c < "$tmp" | tr -d ' ')"
log "uploading ${size} bytes to s3://${BACKUP_S3_BUCKET}/${key}"
aws s3 cp "$tmp" "s3://${BACKUP_S3_BUCKET}/${key}" --only-show-errors \
  || die "upload to S3 failed"

log "done: s3://${BACKUP_S3_BUCKET}/${key}"
