#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/opt/trade-1}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/trade-1-backups}"
resolved="$(realpath -m "$PROJECT_DIR")"
[[ "$resolved" == "/opt/trade-1" ]] || { echo "Refusing unexpected PROJECT_DIR: $resolved" >&2; exit 1; }
timestamp="$(date -u +%Y%m%d_%H%M%S)"
destination="$BACKUP_ROOT/backup_$timestamp"
install -d -m 700 "$destination"
if [[ -d "$PROJECT_DIR" ]]; then
  rsync -aH --numeric-ids "$PROJECT_DIR/" "$destination/project/"
fi
[[ -f "$PROJECT_DIR/.env" ]] && install -m 600 "$PROJECT_DIR/.env" "$destination/.env"
test -d "$destination/project" || { echo "Backup verification failed" >&2; exit 1; }
printf '%s\n' "$destination"
