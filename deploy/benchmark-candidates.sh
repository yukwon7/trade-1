#!/usr/bin/env bash
set -euo pipefail

USER_DATA="${1:-/opt/trade-1/research/user_data}"
if [[ $# -gt 0 ]]; then
  shift
fi
IMAGE="${FREQTRADE_IMAGE:-freqtradeorg/freqtrade:stable}"
TIMERANGE="${BACKTEST_TIMERANGE:-20251221-20260618}"
strategies=("$@")
if [[ ${#strategies[@]} -eq 0 ]]; then
  strategies=(FSampleStrategy FAdxSmaStrategy FReinforcedStrategy)
fi
extra_args=()
if [[ -n "${BACKTEST_STAKE_AMOUNT:-}" ]]; then
  extra_args+=(--stake-amount "$BACKTEST_STAKE_AMOUNT")
fi
if [[ "${BACKTEST_ENABLE_PROTECTIONS:-0}" == "1" ]]; then
  extra_args+=(--enable-protections)
fi

for strategy in "${strategies[@]}"; do
  echo "===== $strategy ====="
  log="/tmp/backtest-$strategy.log"
  if docker run --rm --memory=900m --memory-swap=4g --cpus=0.8 \
    -v "$USER_DATA:/freqtrade/user_data" "$IMAGE" backtesting \
    --config /freqtrade/user_data/config.json \
    --strategy "$strategy" \
    --strategy-path /freqtrade/user_data/strategies \
    --timerange "$TIMERANGE" --cache none --export none "${extra_args[@]}" >"$log" 2>&1; then
    grep -E '^│ TOTAL|^│ Backtested|Total profit|Absolute profit|Max drawdown|Max Drawdown|Max balance drawdown|Final balance|Profit factor|Sharpe|Sortino|Calmar|Long / Short trades|Long / Short profit' "$log" | tail -n 40 || true
  else
    echo "FAILED"
    tail -n 40 "$log"
  fi
done
