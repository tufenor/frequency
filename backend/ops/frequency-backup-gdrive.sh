#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="/opt/frequency/docker-compose.yml"
BACKUP_DIR="/var/lib/docker/volumes/frequency_frequency_backups/_data"
REMOTE="gdrive:FrequencyGym/backups"
LOG_TAG="frequency-backup-gdrive"

mkdir -p "$BACKUP_DIR"

docker compose -f "$COMPOSE_FILE" exec -T app \
  python /app/backend/ops/backup_postgres.py

rclone copy "$BACKUP_DIR" "$REMOTE" \
  --include 'frequency_*.dump.age' \
  --checksum \
  --transfers 1 \
  --checkers 2 \
  --log-level INFO

rclone check "$BACKUP_DIR" "$REMOTE" \
  --one-way \
  --include 'frequency_*.dump.age' \
  --size-only

rclone delete "$REMOTE" \
  --min-age 90d \
  --include 'frequency_*.dump.age' \
  --drive-use-trash=false

logger -t "$LOG_TAG" "Backup PostgreSQL criptografado conferido no Google Drive"
