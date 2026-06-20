#!/usr/bin/env bash
set -euo pipefail

USER_DATA="${USER_DATA:-/opt/trade-1/research/user_data}"
RESULT_DIR="${RESULT_DIR:-/opt/trade-1/research/results}"
IMAGE="${FREQTRADE_IMAGE:-freqtradeorg/freqtrade:stable}"
FEE="${BACKTEST_FEE:-0.0002}"
default_models="ModelEmaAdxTrend ModelBollingerRsiReversion ModelDonchianAtrBreakout ModelMacdMomentum ModelSupertrendConsensus"
read -r -a models <<< "${BACKTEST_MODELS:-$default_models}"
read -r -a ranges <<< "${BACKTEST_RANGES:-20250618-20260318 20260318-20260619}"

install -d -o 1000 -g 1000 -m 750 "$RESULT_DIR"
: > "$RESULT_DIR/summary.txt"

for timerange in "${ranges[@]}"; do
  for model in "${models[@]}"; do
    log="$RESULT_DIR/${timerange}-${model}.log"
    echo "START $timerange $model" | tee -a "$RESULT_DIR/summary.txt"
    if docker run --rm --memory=900m --memory-swap=4g --cpus=0.8 \
      -v "$USER_DATA:/freqtrade/user_data" "$IMAGE" backtesting \
      --config /freqtrade/user_data/config.json \
      --strategy "$model" \
      --timerange "$timerange" \
      --cache none --export none --fee "$FEE" > "$log" 2>&1; then
      grep "│ $model " "$log" | tail -1 | tee -a "$RESULT_DIR/summary.txt" || true
    else
      echo "FAILED $timerange $model" | tee -a "$RESULT_DIR/summary.txt"
      tail -n 30 "$log" >> "$RESULT_DIR/summary.txt"
    fi
    chown 1000:1000 "$log" "$RESULT_DIR/summary.txt"
  done
done
