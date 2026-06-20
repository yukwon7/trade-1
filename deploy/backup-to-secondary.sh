#!/usr/bin/env bash
set -euo pipefail

TARGET="${TRADE_BACKUP_TARGET:-ubuntu@140.245.73.101:/opt/trade-1-backup/}"
KEY="${TRADE_BACKUP_KEY:-/root/.ssh/trade-1-backup}"
ARCHIVE="${TRADE_BACKUP_ARCHIVE:-/var/lib/trade-1-backup/trade-1-freqtrade-backup.tar.gz}"

[[ -r "$KEY" ]] || { echo "Backup SSH key is not readable: $KEY" >&2; exit 1; }
[[ -d /opt/trade-1/user_data ]] || { echo "Freqtrade user_data directory is missing" >&2; exit 1; }

tmp="$(mktemp "${ARCHIVE}.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
tar --exclude='user_data/logs/*' --exclude='user_data/backtest_results/*' -czf "$tmp" -C /opt/trade-1 user_data
tar -tzf "$tmp" >/dev/null
mv -f "$tmp" "$ARCHIVE"
chmod 600 "$ARCHIVE"
rsync -az --chmod=F600,D700 -e "ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=yes" "$ARCHIVE" "$TARGET"
