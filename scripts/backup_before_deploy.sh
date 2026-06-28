#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

target="${1:-config}"
case "$target" in
  config|project) ;;
  *) echo "usage: $0 [config|project]" >&2; exit 2 ;;
esac

timestamp="$(date -u +%Y%m%d_%H%M%S)"
backup_dir="backup_${timestamp}_${target}"
mkdir -p "$backup_dir"

if [[ "$target" == "config" ]]; then
  cp -a config "$backup_dir/"
else
  rsync -a --exclude .env --exclude .venv --exclude data --exclude logs ./ "$backup_dir/project/"
fi

echo "$backup_dir"
