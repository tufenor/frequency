#!/usr/bin/env bash
set -Eeuo pipefail

LOG_TAG="frequency-maintenance"
STATUS_DIR="/var/lib/frequency"
STATUS_FILE="$STATUS_DIR/disk-status.json"
THRESHOLD=70

mkdir -p "$STATUS_DIR"

# Build cache is disposable; never remove images, volumes, containers, app data or backups.
if command -v docker >/dev/null 2>&1; then
  if ! docker builder prune -af --filter until=168h >/var/log/frequency-builder-prune.log 2>&1; then
    logger -t "$LOG_TAG" -p warning -- "Não foi possível limpar o cache antigo do Docker; verifique /var/log/frequency-builder-prune.log"
  fi
fi

used="$(df --output=pcent / | tail -n 1 | tr -dc '0-9')"
used="${used:-0}"
available="$(df --output=avail / | tail -n 1 | tr -d ' ' | tr -d '\n')"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$STATUS_FILE" <<EOF
{"checked_at":"$now","used_percent":$used,"available_kb":$available,"threshold_percent":$THRESHOLD}
EOF
chmod 0644 "$STATUS_FILE"

if [ "$used" -ge "$THRESHOLD" ]; then
  logger -t "$LOG_TAG" -p warning -- "Disco do VPS em ${used}%: revisar backups e artefatos antigos"
else
  logger -t "$LOG_TAG" -- "Manutenção concluída; disco em ${used}%"
fi
