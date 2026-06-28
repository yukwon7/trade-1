#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
[[ "${SERVER_ROLE:-}" == "analysis" ]] || { echo "SERVER_ROLE=analysis required" >&2; exit 1; }

: "${RSYNC_SSH_KEY:?RSYNC_SSH_KEY required}"
: "${RSYNC_USER:?RSYNC_USER required}"
: "${PAPER_HOST:?PAPER_HOST required}"

backup="${1:-latest}"
remote_dir="/opt/trade-1"

ssh -i "$RSYNC_SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$RSYNC_USER@$PAPER_HOST" \
  "set -euo pipefail
   cd '$remote_dir'
   if [[ '$backup' == latest ]]; then
     selected=\$(ls -dt backups/config_* 2>/dev/null | head -n 1)
   else
     selected='$backup'
   fi
   [[ -n \"\${selected:-}\" && -d \"\$selected\" ]] || { echo 'backup not found' >&2; exit 1; }
   cp -a \"\$selected\"/strategy_config.json \"\$selected\"/risk_config.json \"\$selected\"/selected_symbols.json config/
   echo \"rolled back from \$selected\""
