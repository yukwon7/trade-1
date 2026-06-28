#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
[[ "${SERVER_ROLE:-}" == "analysis" ]] || { echo "SERVER_ROLE=analysis required" >&2; exit 1; }

.venv/bin/python -m server_a.hermes.main

if [[ "${DEPLOY_CONFIG:-0}" == "1" ]]; then
  scripts/deploy_server_b_config_only.sh
fi
