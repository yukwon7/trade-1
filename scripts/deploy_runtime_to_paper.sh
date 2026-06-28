#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "deploy_runtime_to_paper.sh is deprecated; using config-only deployment."
exec scripts/deploy_server_b_config_only.sh
