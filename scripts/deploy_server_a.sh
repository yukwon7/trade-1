#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing; do not recreate it here" >&2; exit 1; }
set -a; source .env; set +a
[[ "${SERVER_ROLE:-}" == "analysis" ]] || { echo "SERVER_ROLE=analysis required" >&2; exit 1; }

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p data logs config

.venv/bin/python -m compileall .
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m server_a.hermes.main --no-persist

echo "Server A deployment checks passed. Install systemd/hermes-analysis.service manually if needed."
