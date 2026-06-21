#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m reports.daily_report
.venv/bin/python -m analytics.parameter_optimizer
scripts/deploy_runtime_to_paper.sh
