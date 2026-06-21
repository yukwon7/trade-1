#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/opt/trade-1}"
ENV_FILE="$PROJECT_DIR/.env"
umask 077
install -d -m 750 "$PROJECT_DIR"
if [[ -s "$ENV_FILE" ]]; then
  chmod 600 "$ENV_FILE"
  exit 0
fi
SERVER_ROLE="${SERVER_ROLE:?SERVER_ROLE must be paper or analysis}"
[[ "$SERVER_ROLE" == "paper" || "$SERVER_ROLE" == "analysis" ]] || exit 1
export PROJECT_DIR SERVER_ROLE
python3 - <<'PY'
import json, os
from pathlib import Path

project = Path(os.environ["PROJECT_DIR"])
token = chat_id = api_key = secret = ""
telegram = Path("/etc/trade-1/telegram.json")
if telegram.exists():
    data = json.loads(telegram.read_text())
    section = data.get("telegram", data)
    token = str(section.get("token", ""))
    chat_id = str(section.get("chat_id", ""))
config = project / "user_data/config.json"
if config.exists():
    data = json.loads(config.read_text())
    exchange = data.get("exchange", {})
    api_key = str(exchange.get("key", ""))
    secret = str(exchange.get("secret", ""))
lines = {
    "SERVER_ROLE": os.environ["SERVER_ROLE"],
    "PROJECT_DIR": str(project),
    "DATA_DIR": str(project / "data"),
    "CONFIG_DIR": str(project / "config"),
    "DATABASE_PATH": str(project / "data/trades.db"),
    "TELEGRAM_BOT_TOKEN": token,
    "TELEGRAM_CHAT_ID": chat_id,
    "BINANCE_API_KEY": api_key,
    "BINANCE_SECRET_KEY": secret,
    "PAPER_HOST": os.environ.get("PAPER_HOST", "168.107.21.178"),
    "ANALYSIS_HOST": os.environ.get("ANALYSIS_HOST", "140.245.73.101"),
    "RSYNC_USER": os.environ.get("RSYNC_USER", "ubuntu"),
    "RSYNC_SSH_KEY": os.environ.get(
        "RSYNC_SSH_KEY",
        "/root/.ssh/trade-1-backup" if os.environ["SERVER_ROLE"] == "paper"
        else "/home/ubuntu/.ssh/trade-1-runtime",
    ),
}
(project / ".env").write_text("\n".join(f"{key}={value}" for key, value in lines.items()) + "\n")
PY
chmod 600 "$ENV_FILE"
