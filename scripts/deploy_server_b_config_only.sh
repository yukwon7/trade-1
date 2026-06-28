#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
[[ "${SERVER_ROLE:-}" == "analysis" ]] || { echo "SERVER_ROLE=analysis required" >&2; exit 1; }

.venv/bin/python - <<'PY'
from pathlib import Path
from execution.config_reloader import ConfigReloader

reloader = ConfigReloader(Path("config"))
runtime = reloader.reload()
if reloader.last_errors:
    raise SystemExit(f"invalid config: {reloader.last_errors}")
print("config validated", runtime.strategy.active_strategy_ids, runtime.symbols.symbols)
PY

: "${RSYNC_SSH_KEY:?RSYNC_SSH_KEY required}"
: "${RSYNC_USER:?RSYNC_USER required}"
: "${PAPER_HOST:?PAPER_HOST required}"

remote_dir="/opt/trade-1"
stamp="$(date -u +%Y%m%d_%H%M%S)"
ssh -i "$RSYNC_SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$RSYNC_USER@$PAPER_HOST" \
  "set -euo pipefail
   cd '$remote_dir'
   mkdir -p backups/config_$stamp
   for file in strategy_config.json risk_config.json selected_symbols.json; do
     if [[ -f config/\$file ]]; then
       cp -a config/\$file backups/config_$stamp/
     fi
   done"

rsync -az --chmod=F640 -e "ssh -i $RSYNC_SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  config/strategy_config.json config/risk_config.json config/selected_symbols.json \
  "$RSYNC_USER@$PAPER_HOST:$remote_dir/config/"

echo "deployed config-only to $PAPER_HOST; remote backup backups/config_$stamp"
