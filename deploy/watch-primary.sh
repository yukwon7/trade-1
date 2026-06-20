#!/usr/bin/env bash
set -euo pipefail

URL="${TRADE_HEALTH_URL:-https://trade1.blockpixel.duckdns.org}"
NETRC="${TRADE_HEALTH_NETRC:-/etc/trade-1/watch.netrc}"
STATE_DIR="${TRADE_WATCH_STATE_DIR:-/var/lib/trade-1-watch}"
mkdir -p "$STATE_DIR"

curl_args=(--silent --show-error --fail --max-time 20)
if [[ -r "$NETRC" ]]; then
  curl_args+=(--netrc-file "$NETRC")
fi

if curl "${curl_args[@]}" "$URL" >/dev/null; then
  date --iso-8601=seconds > "$STATE_DIR/last-success"
  rm -f "$STATE_DIR/last-failure" "$STATE_DIR/consecutive-failures"
else
  date --iso-8601=seconds > "$STATE_DIR/last-failure"
  failures=0
  if [[ -r "$STATE_DIR/consecutive-failures" ]]; then
    read -r failures < "$STATE_DIR/consecutive-failures" || failures=0
  fi
  failures=$((failures + 1))
  printf '%s\n' "$failures" > "$STATE_DIR/consecutive-failures"
  logger -p daemon.err -t trade-1-watch "Primary dashboard check failed ($failures consecutive): $URL"
  exit 1
fi
