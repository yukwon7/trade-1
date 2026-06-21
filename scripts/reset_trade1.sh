#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/opt/trade-1}"
resolved="$(realpath -m "$PROJECT_DIR")"
[[ "$resolved" == "/opt/trade-1" ]] || { echo "Unsafe PROJECT_DIR: $resolved" >&2; exit 1; }
[[ "${SERVER_ROLE:-}" == "paper" || "${SERVER_ROLE:-}" == "analysis" ]] || { echo "Invalid SERVER_ROLE" >&2; exit 1; }
ENV_FILE="$PROJECT_DIR/.env"
[[ -f "$ENV_FILE" ]] || { echo ".env missing" >&2; exit 1; }
for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID BINANCE_API_KEY BINANCE_SECRET_KEY; do
  grep -q "^${key}=" "$ENV_FILE" || { echo "$key missing from .env" >&2; exit 1; }
done
backup="$(bash "$(dirname "$0")/backup_old_project.sh")"
[[ -d "$backup/project" && -f "$backup/.env" ]] || { echo "Backup incomplete: $backup" >&2; exit 1; }
env_copy="$(mktemp)"
install -m 600 "$ENV_FILE" "$env_copy"
find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 ! -name '.env' -exec rm -rf -- {} +
install -m 600 "$env_copy" "$ENV_FILE"
rm -f "$env_copy"
set -a; source "$ENV_FILE"; set +a
curl -fsS --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=trade-1 reset complete (${SERVER_ROLE}); backup: ${backup}" >/dev/null || true
printf 'Reset complete. Backup: %s\n' "$backup"
