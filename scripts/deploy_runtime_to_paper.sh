#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
[[ "$SERVER_ROLE" == "analysis" ]] || { echo "analysis role required" >&2; exit 1; }
files=()
[[ -f config/config_override.json ]] && files+=(config/config_override.json)
[[ -f config/selected_symbols.json ]] && files+=(config/selected_symbols.json)
((${#files[@]})) || exit 0
rsync -az --chmod=F640 -e "ssh -i $RSYNC_SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "${files[@]}" "$RSYNC_USER@$PAPER_HOST:/opt/trade-1/config/"
