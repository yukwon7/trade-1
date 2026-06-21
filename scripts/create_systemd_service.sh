#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
if [[ "$SERVER_ROLE" == "paper" ]]; then
  install -m 644 systemd/trade1-paper.service /etc/systemd/system/trade1-paper.service
  systemctl daemon-reload
  systemctl enable --now trade1-paper.service
else
  install -m 644 systemd/trade1-analysis.service /etc/systemd/system/trade1-analysis.service
  systemctl daemon-reload
fi
