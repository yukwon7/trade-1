#!/usr/bin/env bash
set -euo pipefail

USER_DATA="${USER_DATA:-/opt/trade-1/research/user_data}"
IMAGE="${FREQTRADE_IMAGE:-freqtradeorg/freqtrade:stable}"
STRATEGY="${WINNER_STRATEGY:-ModelMacdMomentum}"
TIMERANGE="${VALIDATION_TIMERANGE:-20260318-20260619}"
LOG="${VALIDATION_LOG:-/opt/trade-1/research/winner-lookahead.log}"

docker run --rm --memory=900m --memory-swap=4g --cpus=0.8 \
  -v "$USER_DATA:/freqtrade/user_data" "$IMAGE" lookahead-analysis \
  --config /freqtrade/user_data/config.json \
  --config /freqtrade/user_data/lookahead.config.json \
  --strategy "$STRATEGY" \
  --timerange "$TIMERANGE" \
  --fee 0.0002 \
  --minimum-trade-amount 20 \
  --targeted-trade-amount 50 \
  --lookahead-analysis-exportfilename /freqtrade/user_data/backtest_results/winner-lookahead.csv \
  > "$LOG" 2>&1

grep -E "strategy|filename|bias|lookahead|ModelMacdMomentum" "$LOG" | tail -30
