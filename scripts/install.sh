#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
[[ "$SERVER_ROLE" == "paper" || "$SERVER_ROLE" == "analysis" ]] || exit 1
umask 027
install -d -m 750 data config logs
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3-venv
fi
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install --requirement requirements.txt
chmod 600 .env
chmod +x scripts/*.sh
old_units=(
  trade-freqtrade.service trade-watch.service trade-watch.timer
  trade-backup.service trade-backup.timer trade-learning-sync.service trade-learning-sync.timer
  trade-learning-review-daily.service trade-learning-review-daily.timer
  trade-learning-review-weekly.service trade-learning-review-weekly.timer
  trade-learning-review-monthly.service trade-learning-review-monthly.timer
)
for unit in "${old_units[@]}"; do
  sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
  sudo rm -f "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo scripts/create_systemd_service.sh
cron_file="/etc/cron.d/trade1"
if [[ "$SERVER_ROLE" == "paper" ]]; then
  printf '55 * * * * root cd /opt/trade-1 && scripts/sync_trades_to_analysis.sh >> logs/sync.log 2>&1\n' | sudo tee "$cron_file" >/dev/null
else
  {
    printf '0 0 * * * root cd /opt/trade-1 && scripts/run_analysis.sh >> logs/analysis.log 2>&1\n'
    printf '7 */4 * * * root cd /opt/trade-1 && scripts/run_scanner.sh >> logs/scanner.log 2>&1\n'
  } | sudo tee "$cron_file" >/dev/null
fi
sudo chmod 644 "$cron_file"
