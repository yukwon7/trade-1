#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
if [[ "$ROLE" != "primary" && "$ROLE" != "standby" ]]; then
  echo "Usage: $0 {primary|standby}" >&2
  exit 2
fi

BACKUP_KEY="${TRADE_BACKUP_KEY:-/root/.ssh/trade-1-backup}"
BACKUP_TARGET="${TRADE_BACKUP_TARGET:-ubuntu@140.245.73.101:/opt/trade-1-backup/}"
for command in systemctl docker tar; do
  command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; exit 1; }
done

mem_kb="$(awk '/MemTotal:/ { print $2 }' /proc/meminfo)"
swap_mb="$(free -m | awk '/Swap:/ { print $2 }')"
disk_mb="$(df -Pm /opt | awk 'NR==2 { print $4 }')"
[[ -n "$mem_kb" && "$mem_kb" -ge 850000 ]] || { echo "Insufficient physical memory." >&2; exit 1; }
[[ -n "$swap_mb" && "$swap_mb" -ge 7000 ]] || { echo "At least 7 GB swap is required." >&2; exit 1; }
[[ -n "$disk_mb" && "$disk_mb" -ge 8000 ]] || { echo "At least 8 GB free disk is required." >&2; exit 1; }
docker info >/dev/null

case "$ROLE" in
  primary)
    for command in caddy rsync ssh openssl; do
      command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; exit 1; }
    done
    [[ -r "${TRADE_DASHBOARD_HASH_FILE:-/etc/trade-1/dashboard-password.hash}" ]] || { echo "Dashboard hash file is missing." >&2; exit 1; }
    [[ -r "${TRADE_API_PASSWORD_FILE:-}" ]] || { echo "TRADE_API_PASSWORD_FILE is missing." >&2; exit 1; }
    [[ -r "$BACKUP_KEY" ]] || { echo "Backup SSH key is missing: $BACKUP_KEY" >&2; exit 1; }
    [[ -n "$BACKUP_TARGET" ]] || { echo "TRADE_BACKUP_TARGET must not be empty." >&2; exit 1; }
    ;;
  standby)
    for command in curl rsync ssh; do
      command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; exit 1; }
    done
    [[ -r "${TRADE_HEALTH_PASSWORD_FILE:-}" ]] || { echo "TRADE_HEALTH_PASSWORD_FILE is missing." >&2; exit 1; }
    backup_user="${TRADE_BACKUP_USER:-ubuntu}"
    id "$backup_user" >/dev/null 2>&1 || { echo "Backup user does not exist: $backup_user" >&2; exit 1; }
    ;;
esac

echo "Preflight checks passed for $ROLE."
