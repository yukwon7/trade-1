#!/usr/bin/env bash
set -euo pipefail

SIZE_GB="${TRADE_SWAP_GB:-8}"
SWAPFILE="${TRADE_SWAP_FILE:-/swapfile.trade}"
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ "$SIZE_GB" =~ ^[0-9]+$ && "$SIZE_GB" -ge 2 && "$SIZE_GB" -le 16 ]] || {
  echo "TRADE_SWAP_GB must be an integer from 2 to 16." >&2
  exit 2
}
command -v fallocate >/dev/null || { echo "fallocate is required." >&2; exit 1; }

swapoff "$SWAPFILE" 2>/dev/null || true
truncate -s 0 "$SWAPFILE"
fallocate -l "${SIZE_GB}G" "$SWAPFILE"
chmod 600 "$SWAPFILE"
mkswap "$SWAPFILE" >/dev/null
swapon --priority 10 "$SWAPFILE"

sed -i "\\|^${SWAPFILE}[[:space:]]|d" /etc/fstab
printf '%s none swap sw,pri=10 0 0\n' "$SWAPFILE" >> /etc/fstab
cat > /etc/sysctl.d/99-trade-1-memory.conf <<EOF
vm.swappiness=15
vm.vfs_cache_pressure=100
EOF
sysctl --system >/dev/null

echo "Added ${SIZE_GB}GB swap at $SWAPFILE."
free -h
