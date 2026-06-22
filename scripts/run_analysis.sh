#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m analytics.tournament_evaluator
scripts/deploy_runtime_to_paper.sh
