#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
[[ "${SERVER_ROLE:-}" == "analysis" ]] || { echo "SERVER_ROLE=analysis required" >&2; exit 1; }

: "${RSYNC_SSH_KEY:?RSYNC_SSH_KEY required}"
: "${RSYNC_USER:?RSYNC_USER required}"
: "${PAPER_HOST:?PAPER_HOST required}"

mkdir -p data
rsync -az --chmod=F600 -e "ssh -i $RSYNC_SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$RSYNC_USER@$PAPER_HOST:/opt/trade-1/data/trades.db" data/trades.db

echo "synced Server B trades.db into Server A data/trades.db"
