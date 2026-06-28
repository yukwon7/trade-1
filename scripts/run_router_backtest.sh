#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m analytics.router_backtester \
  --days "${ROUTER_BACKTEST_DAYS:-0}" \
  --step "${ROUTER_BACKTEST_STEP:-12}" \
  "$@"

if [[ "${DEPLOY_CONFIG:-0}" == "1" ]]; then
  scripts/deploy_server_b_config_only.sh
fi
