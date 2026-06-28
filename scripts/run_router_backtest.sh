#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m analytics.router_backtester \
  --days "${ROUTER_BACKTEST_DAYS:-0}" \
  --step "${ROUTER_BACKTEST_STEP:-12}" \
  "$@"
scripts/deploy_runtime_to_paper.sh
