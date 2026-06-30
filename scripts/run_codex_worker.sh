#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/trade-1}"
CONFIG_DIR="${CONFIG_DIR:-$PROJECT_DIR/config}"

cd "$PROJECT_DIR"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"

exec "$PYTHON_BIN" -m server_a.hermes.codex_bridge run-once \
  --project-dir "$PROJECT_DIR" \
  --config-dir "$CONFIG_DIR"
