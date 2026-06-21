#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HASH_FILE="${TRADE_DASHBOARD_HASH_FILE:-/etc/trade-1/dashboard-password.hash}"
PASSWORD_FILE="${TRADE_API_PASSWORD_FILE:-}"
BACKUP_KEY="${TRADE_BACKUP_KEY:-/root/.ssh/trade-1-backup}"
BACKUP_TARGET="${TRADE_BACKUP_TARGET:-ubuntu@140.245.73.101:/opt/trade-1-backup/}"
FREQTRADE_IMAGE="${FREQTRADE_IMAGE:-freqtradeorg/freqtrade:stable}"
START_FREQTRADE=0

if [[ "${1:-}" == "--start-freqtrade" ]]; then
  START_FREQTRADE=1
elif [[ $# -ne 0 ]]; then
  echo "Usage: sudo TRADE_DASHBOARD_HASH_FILE=/secure/hash TRADE_API_PASSWORD_FILE=/secure/password $0 [--start-freqtrade]" >&2
  exit 2
fi

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
for command in docker caddy systemctl rsync ssh tar install sed grep openssl; do
  command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; exit 1; }
done
[[ -s "$HASH_FILE" ]] || { echo "Caddy password hash file is missing or empty: $HASH_FILE" >&2; exit 1; }
[[ -n "$PASSWORD_FILE" && -s "$PASSWORD_FILE" ]] || { echo "Set TRADE_API_PASSWORD_FILE to a readable password file." >&2; exit 1; }
[[ -r "$BACKUP_KEY" ]] || { echo "Backup SSH key is not readable: $BACKUP_KEY" >&2; exit 1; }

hash="$(tr -d '\r\n' < "$HASH_FILE")"
api_password="$(tr -d '\r\n' < "$PASSWORD_FILE")"
[[ "$api_password" != *[[:space:]]* ]] || { echo "API password must not contain whitespace." >&2; exit 1; }
escaped_hash="$(printf '%s' "$hash" | sed 's/[\/&\\]/\\&/g')"
escaped_password="$(printf '%s' "$api_password" | sed 's/[\/&\\]/\\&/g')"
jwt_secret="$(openssl rand -hex 32)"
ws_token="$(openssl rand -hex 32)"

install -d -m 700 /etc/trade-1 /var/lib/trade-1-backup
install -d -m 750 /opt/trade-1/user_data/{strategies,data,logs,backtest_results,learning}
install -d -o 1000 -g 1000 -m 750 /opt/trade-1/research/user_data/{strategies,data,backtest_results}
install -d -m 755 /opt/trade-1/user_data/patches
install -d -m 750 /etc/caddy /etc/caddy/Caddyfile.d
install -m 644 "$SCRIPT_DIR/freqtrade.service" /etc/systemd/system/trade-freqtrade.service
install -m 644 "$SCRIPT_DIR/trade-learning-sync.service" /etc/systemd/system/trade-learning-sync.service
install -m 644 "$SCRIPT_DIR/trade-learning-sync.timer" /etc/systemd/system/trade-learning-sync.timer
install -m 644 "$SCRIPT_DIR/trade-learning-review-daily.service" /etc/systemd/system/trade-learning-review-daily.service
install -m 644 "$SCRIPT_DIR/trade-learning-review-daily.timer" /etc/systemd/system/trade-learning-review-daily.timer
install -m 644 "$SCRIPT_DIR/trade-learning-review-weekly.service" /etc/systemd/system/trade-learning-review-weekly.service
install -m 644 "$SCRIPT_DIR/trade-learning-review-weekly.timer" /etc/systemd/system/trade-learning-review-weekly.timer
install -m 644 "$SCRIPT_DIR/trade-learning-review-monthly.service" /etc/systemd/system/trade-learning-review-monthly.service
install -m 644 "$SCRIPT_DIR/trade-learning-review-monthly.timer" /etc/systemd/system/trade-learning-review-monthly.timer
install -m 644 "$SCRIPT_DIR/AggressiveSafeStrategy.py" /opt/trade-1/user_data/strategies/AggressiveSafeStrategy.py
install -m 644 "$SCRIPT_DIR/community_strategies/"*.py /opt/trade-1/user_data/strategies/
install -m 644 "$SCRIPT_DIR/trade_learning.py" /opt/trade-1/user_data/strategies/trade_learning.py
install -m 644 "$SCRIPT_DIR/sync_learning.py" /opt/trade-1/user_data/strategies/sync_learning.py
install -m 644 "$SCRIPT_DIR/review_learning.py" /opt/trade-1/user_data/strategies/review_learning.py
install -m 644 "$SCRIPT_DIR/recover_journal_trades.py" /opt/trade-1/user_data/strategies/recover_journal_trades.py
install -o 1000 -g 1000 -m 644 "$SCRIPT_DIR/research/FiveModelStrategies.py" /opt/trade-1/research/user_data/strategies/FiveModelStrategies.py
install -m 644 "$SCRIPT_DIR/research/FiveModelStrategies.py" /opt/trade-1/user_data/strategies/FiveModelStrategies.py
install -o 1000 -g 1000 -m 644 "$SCRIPT_DIR/backtest.config.json" /opt/trade-1/research/user_data/config.json
install -o 1000 -g 1000 -m 644 "$SCRIPT_DIR/research/lookahead.config.json" /opt/trade-1/research/user_data/lookahead.config.json
install -m 644 "$SCRIPT_DIR/telegram_ko/sitecustomize.py" /opt/trade-1/user_data/patches/sitecustomize.py
install -m 755 "$SCRIPT_DIR/configure-telegram.sh" /usr/local/sbin/trade-1-configure-telegram
install -m 755 "$SCRIPT_DIR/set_telegram_commands.py" /usr/local/sbin/trade-1-set-telegram-commands
install -m 755 "$SCRIPT_DIR/research/run-five-model-backtests.sh" /usr/local/sbin/trade-1-run-five-model-backtests
install -m 755 "$SCRIPT_DIR/research/validate-winner.sh" /usr/local/sbin/trade-1-validate-winner
if [[ ! -e /etc/trade-1/telegram.json ]]; then
  install -o root -g 1000 -m 640 "$SCRIPT_DIR/telegram.disabled.json" /etc/trade-1/telegram.json
fi
sed -e "s/__API_PASSWORD__/$escaped_password/" -e "s/__JWT_SECRET__/$jwt_secret/" -e "s/__WS_TOKEN__/$ws_token/" \
  "$SCRIPT_DIR/config.json.template" > /opt/trade-1/user_data/config.json
chmod 600 /opt/trade-1/user_data/config.json
chown -R 1000:1000 /opt/trade-1/user_data
printf 'FREQTRADE_IMAGE=%s\n' "$FREQTRADE_IMAGE" > /etc/trade-1/freqtrade.env
chmod 600 /etc/trade-1/freqtrade.env

install -m 755 "$SCRIPT_DIR/backup-to-secondary.sh" /usr/local/sbin/trade-1-backup
install -m 644 "$SCRIPT_DIR/trade-backup.service" /etc/systemd/system/trade-backup.service
install -m 644 "$SCRIPT_DIR/trade-backup.timer" /etc/systemd/system/trade-backup.timer
cat > /etc/trade-1/backup.env <<EOF
TRADE_BACKUP_TARGET=$BACKUP_TARGET
TRADE_BACKUP_KEY=$BACKUP_KEY
EOF
chmod 600 /etc/trade-1/backup.env

sed "s/__PASSWORD_HASH__/$escaped_hash/" "$SCRIPT_DIR/Caddyfile.fragment" > /etc/caddy/Caddyfile.d/trade-1.caddy
chmod 640 /etc/caddy/Caddyfile.d/trade-1.caddy
if getent group caddy >/dev/null; then
  chown root:caddy /etc/caddy/Caddyfile.d/trade-1.caddy
fi
if ! grep -Fqx 'import Caddyfile.d/*.caddy' /etc/caddy/Caddyfile; then
  printf '\nimport Caddyfile.d/*.caddy\n' >> /etc/caddy/Caddyfile
fi

docker pull "$FREQTRADE_IMAGE"
docker run --rm -v /opt/trade-1/user_data:/freqtrade/user_data "$FREQTRADE_IMAGE" \
  show-config --config /freqtrade/user_data/config.json >/dev/null
docker run --rm -v /opt/trade-1/user_data:/freqtrade/user_data -v /etc/trade-1/telegram.json:/run/secrets/telegram.json:ro "$FREQTRADE_IMAGE" \
  show-config --config /freqtrade/user_data/config.json --config /run/secrets/telegram.json >/dev/null
docker run --rm -v /opt/trade-1/user_data:/freqtrade/user_data "$FREQTRADE_IMAGE" \
  list-strategies | grep -Fq ModelMacdMomentumActive30
caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now caddy
systemctl reload caddy
systemctl enable --now trade-backup.timer
systemctl enable --now trade-learning-sync.timer
systemctl enable --now trade-learning-review-daily.timer
systemctl enable --now trade-learning-review-weekly.timer
systemctl enable --now trade-learning-review-monthly.timer

if [[ $START_FREQTRADE -eq 1 ]]; then
  systemctl enable --now trade-freqtrade
else
  systemctl disable --now trade-freqtrade >/dev/null 2>&1 || true
  echo "Freqtrade remains stopped until backtesting is complete."
fi

echo "Primary Freqtrade installation complete."
