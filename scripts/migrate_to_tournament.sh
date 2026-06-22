#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
database="${DATABASE_PATH:-/opt/trade-1/data/trades.db}"
project="$(realpath /opt/trade-1)"
resolved="$(realpath -m "$database")"
[[ "$resolved" == "$project"/data/* ]] || { echo "unsafe database path: $resolved" >&2; exit 1; }
archive="data/archive/pre_tournament_$(date -u +%Y%m%d_%H%M%S)"
install -d -m 750 "$archive"
for file in "$resolved" "$resolved-wal" "$resolved-shm"; do
  [[ -f "$file" ]] && cp -a "$file" "$archive/"
done
[[ -f "$resolved" ]] && [[ -f "$archive/$(basename "$resolved")" ]] || {
  [[ ! -f "$resolved" ]] || { echo "database backup failed" >&2; exit 1; }
}
rm -f -- "$resolved" "$resolved-wal" "$resolved-shm"
echo "old database archived at $archive"
