#!/usr/bin/env bash
# Restore a backup into a NEW, named throwaway database. Never touches the live database.
#
# Usage:
#   scripts/restore_postgres.sh [--compare-live] <backup> <new_db_name>
#     <backup>        s3://bucket/key.sql.gz, or a local .sql.gz file
#     <new_db_name>   lowercase letters, digits and underscores; must not exist yet
#     --compare-live  also print a diff of row counts against the live database
#
# DATABASE_URL (environment or repo .env) must point at the same Postgres server; its user needs CREATEDB.
# Downloading from S3 needs credentials that can read the bucket (the server role is write-only).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

dotenv_value() {
  local file="$REPO_DIR/.env"
  [[ -f "$file" ]] || return 0
  { grep -E "^$1=" "$file" || true; } | tail -n 1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"
}

die() { echo "restore_postgres: ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

compare_live=0
if [[ "${1:-}" == "--compare-live" ]]; then compare_live=1; shift; fi
[[ $# -eq 2 ]] || usage
backup="$1"
new_db="$2"

[[ "$new_db" =~ ^[a-z][a-z0-9_]{0,62}$ ]] || die "database name must match ^[a-z][a-z0-9_]{0,62}\$"

DATABASE_URL="${DATABASE_URL:-$(dotenv_value DATABASE_URL)}"
[[ -n "$DATABASE_URL" ]] || die "DATABASE_URL is not set"
DATABASE_URL="$(sed -E 's#^(postgres(ql)?)\+[A-Za-z0-9]+://#\1://#' <<<"$DATABASE_URL")"

live_db="$(sed -E 's#^.*/([^/?]+)(\?.*)?$#\1#' <<<"$DATABASE_URL")"
[[ "$new_db" != "$live_db" ]] || die "refusing to restore into the live database (${live_db})"
target_url="$(sed -E "s#/[^/?]+(\?.*)?\$#/${new_db}\1#" <<<"$DATABASE_URL")"

tmp=""
cleanup() { [[ -z "$tmp" ]] || rm -f "$tmp"; }
trap cleanup EXIT

if [[ "$backup" == s3://* ]]; then
  tmp="$(mktemp "${TMPDIR:-/tmp}/clew_restore.XXXXXX")"
  echo "Downloading ${backup}"
  aws s3 cp "$backup" "$tmp" --only-show-errors || die "download failed"
  file="$tmp"
else
  [[ -f "$backup" ]] || die "no such file: ${backup}"
  file="$backup"
fi

gzip -t "$file" || die "gzip integrity check failed"

exists="$(psql "$DATABASE_URL" -Atq -c "SELECT 1 FROM pg_database WHERE datname = '${new_db}'")" \
  || die "cannot query the server with DATABASE_URL"
[[ -z "$exists" ]] || die "database ${new_db} already exists; pick a new name or drop it yourself"

echo "Creating database ${new_db}"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE \"${new_db}\"" \
  || die "CREATE DATABASE failed"

echo "Restoring (single transaction)"
if ! gzip -dc "$file" | psql "$target_url" -v ON_ERROR_STOP=1 -q --single-transaction > /dev/null; then
  die "restore failed; ${new_db} left in place for inspection (drop it when done)"
fi

row_counts() {
  psql "$1" -Atq -F $'\t' <<'SQL'
SELECT format('SELECT %L, count(*) FROM %I.%I', table_name, table_schema, table_name)
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name \gexec
SQL
}

echo
echo "Row counts in ${new_db}:"
row_counts "$target_url"

if [[ "$compare_live" -eq 1 ]]; then
  echo
  echo "Diff against live (${live_db}); '<' is live, '>' is the restore. Small differences are expected:"
  diff <(row_counts "$DATABASE_URL") <(row_counts "$target_url") && echo "No differences." || true
fi

cat <<EOF

Restored into ${new_db}. Next:
  1. Set DATABASE_URL to the same URL with the database name replaced by ${new_db}, for the commands below only.
  2. Timestamp driven tasks must be run by hand after a restore:
       python -c "from workers.tasks.purge_expired_data import purge_expired_data as t; print(t())"
       python -c "from workers.tasks.purge_deleted_accounts import purge_deleted_accounts as t; print(t())"
  3. TOTP secrets and Cloudflare tokens are unreadable without the original TOTP_ENCRYPTION_KEY (and sessions need JWT_SECRET).
  4. When finished: psql "\$DATABASE_URL" -c 'DROP DATABASE "${new_db}"'
EOF
