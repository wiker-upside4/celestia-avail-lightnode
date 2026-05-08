#!/bin/bash
# Daily DB backup. Stores compressed dump in /home/wiker/dabeat/backups
# and prunes anything older than 7 days.

set -euo pipefail

ENV_FILE=/home/wiker/.dabeat/.env
BACKUP_DIR=/home/wiker/dabeat/backups
TS=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/dabeat_${TS}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Read DB credentials from .env (no echo).
DB_HOST=$(grep ^DB_HOST "$ENV_FILE" | cut -d= -f2-)
DB_PORT=$(grep ^DB_PORT "$ENV_FILE" | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME "$ENV_FILE" | cut -d= -f2-)
DB_USER=$(grep ^DB_USER "$ENV_FILE" | cut -d= -f2-)
DB_PASSWORD=$(grep ^DB_PASSWORD "$ENV_FILE" | cut -d= -f2-)

PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    --no-owner --no-privileges "$DB_NAME" | gzip > "$OUT"

# Prune old backups (>7 days).
find "$BACKUP_DIR" -name 'dabeat_*.sql.gz' -mtime +7 -print -delete

echo "[backup] $(date -Iseconds) wrote $OUT ($(du -h "$OUT" | cut -f1))"
