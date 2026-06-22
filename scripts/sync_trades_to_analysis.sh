#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
[[ "$SERVER_ROLE" == "paper" ]] || { echo "paper role required" >&2; exit 1; }
install -d -m 750 data/sync
.venv/bin/python - <<'PY'
import os, sqlite3
source = sqlite3.connect(os.environ.get("DATABASE_PATH", "data/trades.db"))
target = sqlite3.connect("data/sync/trades.db")
with target:
    source.backup(target)
target.close(); source.close()
PY
rsync -az --chmod=F600 -e "ssh -i $RSYNC_SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  data/sync/trades.db "$RSYNC_USER@$ANALYSIS_HOST:/opt/trade-1/data/trades.db"
if [[ -f config/tournament_control.json ]]; then
  rsync -az --chmod=F640 -e "ssh -i $RSYNC_SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    config/tournament_control.json "$RSYNC_USER@$ANALYSIS_HOST:/opt/trade-1/config/tournament_control.json"
fi
