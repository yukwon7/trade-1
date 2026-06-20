"""Sync Freqtrade API trade history into the persistent learning database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from freqtrade_client import FtRestClient

from trade_learning import rebuild_signal_stats, record_event, upsert_trade_result


CONFIG_PATH = Path("/freqtrade/user_data/config.json")


def load_client() -> FtRestClient:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    api = config["api_server"]
    return FtRestClient(
        "http://127.0.0.1:8080",
        username=api["username"],
        password=api["password"],
    )


def main() -> int:
    client = load_client()
    synced = 0

    trades_response = client.trades(limit=1000)
    for trade in trades_response.get("trades", []):
        if upsert_trade_result(trade):
            synced += 1

    for trade in client.status():
        if upsert_trade_result(trade):
            synced += 1

    rebuild_signal_stats()
    record_event("sync", f"synced {synced} trade rows", {"synced": synced})
    print(f"learning sync complete: {synced} rows")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"learning sync failed: {exc}", file=sys.stderr)
        raise
