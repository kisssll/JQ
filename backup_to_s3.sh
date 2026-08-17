#!/usr/bin/env bash
# backup_to_s3.sh — дамп основной БД проекта в S3 (Timeweb S3, s3.twcstorage.ru).
# (БД otp_service больше нет — OTP свёрнут внутрь приложения, коммит c482669)
# Требует на хосте: pg_dump (postgresql-client) и aws-cli.
# Имя БД берётся из .env (POSTGRES_DB) — прод=default_db (managed Timeweb),
# staging=beauty_platform; хардкод убран, чтобы бэкапился реальный инстанс.
# Настройка cron (ежедневно в 03:00):
#   0 3 * * * cd /opt/rumi/be && ./backup_to_s3.sh >> /opt/rumi/db_backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

# Креды основной БД — из .env этого репозитория
PGHOST="$(grep -E '^POSTGRES_HOST=' .env | cut -d= -f2-)"
PGPORT="$(grep -E '^POSTGRES_PORT=' .env | cut -d= -f2-)"
PGUSER="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)"
PGDB="$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)"
export PGPASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"

# S3 (VK Cloud через панель Timeweb) — из .env этого репозитория
S3_ENDPOINT="$(grep -E '^S3_ENDPOINT=' .env | cut -d= -f2-)"
S3_BUCKET="$(grep -E '^S3_BUCKET=' .env | cut -d= -f2-)"
export AWS_ACCESS_KEY_ID="$(grep -E '^S3_ACCESS_KEY=' .env | cut -d= -f2-)"
export AWS_SECRET_ACCESS_KEY="$(grep -E '^S3_SECRET_KEY=' .env | cut -d= -f2-)"

STAMP="$(date +%Y%m%d_%H%M%S)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

dump_and_upload() {
  local dbname="$1"
  local file="$TMPDIR/${dbname}_${STAMP}.sql.gz"
  echo "[backup] дамп $dbname..."
  pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$dbname" | gzip > "$file"
  echo "[backup] заливка $dbname в s3://$S3_BUCKET/$dbname/..."
  aws --endpoint-url "$S3_ENDPOINT" s3 cp "$file" "s3://$S3_BUCKET/$dbname/$(basename "$file")"
}

dump_and_upload "$PGDB"

echo "[backup] готово: $STAMP"
