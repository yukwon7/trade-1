from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from analytics.stress_tester import _metrics


def analyze_performance(database_path: str | Path, initial_balance: float, limit: int = 50) -> dict[str, Any]:
    rows = _load_rows(database_path, limit)
    metrics = _metrics(rows, initial_balance)
    return {
        "trade_count": metrics["trade_count"],
        "net_pnl": metrics["net_pnl"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown": metrics["max_drawdown"],
        "expectancy": metrics["net_pnl"] / metrics["trade_count"] if metrics["trade_count"] else 0.0,
        "long_short": _split(rows, "direction"),
        "by_symbol": _group(rows, "symbol", initial_balance),
        "by_strategy": _group(rows, "strategy_id", initial_balance),
        "rows": rows,
    }


def _load_rows(database_path: str | Path, limit: int) -> list[dict]:
    path = Path(database_path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        if "tournament_trades" not in tables:
            return []
        rows = connection.execute(
            """
            select strategy_id, symbol, direction, pnl, exit_time, exit_reason
            from tournament_trades
            order by coalesce(exit_time, created_at) desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def _split(rows: list[dict], key: str) -> dict[str, int]:
    output: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN")
        output[value] = output.get(value, 0) + 1
    return output


def _group(rows: list[dict], key: str, initial_balance: float) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for value in sorted({str(row.get(key) or "UNKNOWN") for row in rows}):
        selected = [row for row in rows if str(row.get(key) or "UNKNOWN") == value]
        output[value] = _metrics(selected, initial_balance)
    return output
