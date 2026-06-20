#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PASSWORD_FILE="${TRADE_HEALTH_PASSWORD_FILE:-}"
HEALTH_HOST="${TRADE_HEALTH_HOST:-trade1.blockpixel.duckdns.org}"
HEALTH_USER="${TRADE_HEALTH_USER:-trader}"
BACKUP_USER="${TRADE_BACKUP_USER:-ubuntu}"
FREQTRADE_IMAGE="${FREQTRADE_IMAGE:-freqtradeorg/freqtrade:stable}"

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
for command in docker systemctl curl tar install; do
  command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; exit 1; }
done
[[ -n "$PASSWORD_FILE" && -s "$PASSWORD_FILE" ]] || { echo "Set TRADE_HEALTH_PASSWORD_FILE." >&2; exit 1; }
id "$BACKUP_USER" >/dev/null 2>&1 || { echo "Backup user does not exist: $BACKUP_USER" >&2; exit 1; }

password="$(tr -d '\r\n' < "$PASSWORD_FILE")"
[[ "$password" != *[[:space:]]* ]] || { echo "Dashboard password must not contain whitespace." >&2; exit 1; }
[[ "$HEALTH_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Invalid health host." >&2; exit 1; }
[[ "$HEALTH_USER" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid health user." >&2; exit 1; }

install -d -m 700 /etc/trade-1
install -d -o "$BACKUP_USER" -g "$BACKUP_USER" -m 700 /opt/trade-1-backup
install -d -m 755 /var/lib/trade-1-watch
install -d -m 750 /opt/trade-1/user_data/{strategies,data,logs,backtest_results}
chown -R 1000:1000 /opt/trade-1/user_data
install -m 644 "$SCRIPT_DIR/freqtrade.service" /etc/systemd/system/trade-freqtrade.service
install -m 755 "$SCRIPT_DIR/watch-primary.sh" /usr/local/sbin/trade-1-watch
install -m 755 "$SCRIPT_DIR/promote-standby.sh" /usr/local/sbin/trade-1-promote
install -m 644 "$SCRIPT_DIR/trade-watch.service" /etc/systemd/system/trade-watch.service
install -m 644 "$SCRIPT_DIR/trade-watch.timer" /etc/systemd/system/trade-watch.timer
printf 'FREQTRADE_IMAGE=%s\n' "$FREQTRADE_IMAGE" > /etc/trade-1/freqtrade.env
chmod 600 /etc/trade-1/freqtrade.env
cat > /etc/trade-1/watch.netrc <<EOF
machine $HEALTH_HOST
login $HEALTH_USER
password $password
EOF
chmod 600 /etc/trade-1/watch.netrc
printf 'TRADE_HEALTH_URL=https://%s\n' "$HEALTH_HOST" > /etc/trade-1/watch.env
chmod 600 /etc/trade-1/watch.env

docker pull "$FREQTRADE_IMAGE"
systemctl daemon-reload
systemctl disable --now trade-freqtrade >/dev/null 2>&1 || true
systemctl enable --now trade-watch.timer
echo "Standby Freqtrade installation complete. Service is stopped."
