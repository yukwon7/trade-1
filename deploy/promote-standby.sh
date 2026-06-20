#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--confirm-primary-stopped" ]]; then
  echo "Refusing promotion. Verify the primary Freqtrade container is stopped, then run:"
  echo "sudo $0 --confirm-primary-stopped"
  exit 2
fi
if systemctl is-active --quiet trade-freqtrade; then
  echo "Refusing promotion: local Freqtrade is already active." >&2
  exit 3
fi

archive=/opt/trade-1-backup/trade-1-freqtrade-backup.tar.gz
[[ -s "$archive" ]] || { echo "Backup archive is missing: $archive" >&2; exit 1; }
tar -tzf "$archive" >/dev/null
mkdir -p /opt/trade-1
tar -xzf "$archive" -C /opt/trade-1
systemctl enable --now trade-freqtrade
echo "Standby promoted. Verify http://127.0.0.1:8080, then update DNS."
