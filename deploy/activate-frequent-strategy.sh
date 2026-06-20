#!/usr/bin/env bash
set -euo pipefail

CONFIG=/opt/trade-1/user_data/config.json
IMAGE="${FREQTRADE_IMAGE:-freqtradeorg/freqtrade:stable}"

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
grep -Fq '"dry_run": true' "$CONFIG" || {
  echo "Refusing to change a non-dry-run configuration." >&2
  exit 1
}

cp -a "$CONFIG" "$CONFIG.before-frequent-strategy"
sed -i \
  -e 's/"stake_amount": 100/"stake_amount": 10/' \
  -e 's/"timeframe": "4h"/"timeframe": "5m"/' \
  "$CONFIG"
if ! grep -Fq '"force_entry_enable": true' "$CONFIG"; then
  sed -i '/"cancel_open_orders_on_exit": true,/a\  "force_entry_enable": true,' "$CONFIG"
fi
sed -i '/"protections": \[{"method": "CooldownPeriod", "stop_duration_candles": 12}\],/d' "$CONFIG"

grep -Fq '"stake_amount": 10' "$CONFIG"
grep -Fq '"timeframe": "5m"' "$CONFIG"
grep -Fq '"force_entry_enable": true' "$CONFIG"

docker run --rm \
  -v /opt/trade-1/user_data:/freqtrade/user_data \
  -v /etc/trade-1/telegram.json:/run/secrets/telegram.json:ro \
  "$IMAGE" show-config \
  --config /freqtrade/user_data/config.json \
  --config /run/secrets/telegram.json >/dev/null
docker run --rm -v /opt/trade-1/user_data:/freqtrade/user_data "$IMAGE" \
  list-strategies | grep -Fq FReinforced20Strategy

systemctl daemon-reload
systemctl restart trade-freqtrade

for _ in {1..45}; do
  if docker inspect -f '{{.State.Running}}' trade-freqtrade 2>/dev/null | grep -Fxq true; then
    sleep 5
    docker inspect -f '{{.State.Running}}' trade-freqtrade | grep -Fxq true
    echo "Frequent dry-run strategy activated."
    exit 0
  fi
  sleep 1
done

echo "Freqtrade did not become ready." >&2
exit 1
