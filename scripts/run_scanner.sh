#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m scanner.market_scanner
scripts/deploy_runtime_to_paper.sh
