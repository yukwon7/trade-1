#!/usr/bin/env bash
set -euo pipefail

CONFIG=/etc/trade-1/telegram.json

usage() {
  echo "Usage: sudo $0 TOKEN_FILE CHAT_ID_FILE | --disable" >&2
  exit 2
}

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }

if [[ "${1:-}" == "--disable" && $# -eq 1 ]]; then
  install -d -m 700 /etc/trade-1
  printf '{\n  "telegram": {\n    "enabled": false\n  }\n}\n' > "$CONFIG"
  chown root:1000 "$CONFIG"
  chmod 640 "$CONFIG"
  systemctl restart trade-freqtrade
  echo "Telegram notifications disabled."
  exit 0
fi

[[ $# -eq 2 ]] || usage
[[ -s "$1" && -s "$2" ]] || { echo "Token/chat ID file is missing or empty." >&2; exit 1; }

token="$(tr -d '\r\n' < "$1")"
chat_id="$(tr -d '\r\n' < "$2")"
[[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "Invalid Telegram bot token format." >&2; exit 1; }
[[ "$chat_id" =~ ^-?[0-9]+$ ]] || { echo "Invalid Telegram chat ID format." >&2; exit 1; }

install -d -m 700 /etc/trade-1
umask 077
tmp="$(mktemp /etc/trade-1/telegram.json.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
printf '{\n  "telegram": {\n    "enabled": true,\n    "token": "%s",\n    "chat_id": "%s",\n    "allow_custom_messages": false,\n    "notification_settings": {\n      "status": "on",\n      "warning": "on",\n      "startup": "on",\n      "entry": "on",\n      "entry_fill": "on",\n      "exit": "on",\n      "exit_fill": "on",\n      "protection_trigger": "on",\n      "strategy_msg": "off",\n      "show_candle": "off"\n    }\n  }\n}\n' "$token" "$chat_id" > "$tmp"
mv -f "$tmp" "$CONFIG"
trap - EXIT
chown root:1000 "$CONFIG"
chmod 640 "$CONFIG"

systemctl restart trade-freqtrade
for _ in {1..30}; do
  if docker inspect -f '{{.State.Running}}' trade-freqtrade 2>/dev/null | grep -Fxq true; then
    break
  fi
  sleep 1
done
docker inspect -f '{{.State.Running}}' trade-freqtrade 2>/dev/null | grep -Fxq true
echo "Telegram notifications enabled; Freqtrade is active."
