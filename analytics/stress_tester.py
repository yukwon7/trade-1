from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from config import Settings


MIN_LIVE_TRADES = 30
MIN_LIVE_WIN_RATE = 0.45
MIN_LIVE_PROFIT_FACTOR = 1.20
MAX_LIVE_DRAWDOWN = 0.10


def _value(row, key: str, default=None):
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _as_float(row, key: str, default: float = 0.0) -> float:
    value = _value(row, key, default)
    return float(value) if value is not None else default


def _metrics(rows: Iterable[dict], initial_balance: float) -> dict:
    rows = list(rows)
    pnls = [_as_float(row, "pnl") for row in rows]
    returns = [_as_float(row, "return_pct") for row in rows]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_loss = abs(sum(losses))
    profit_factor = sum(wins) / gross_loss if gross_loss else (10.0 if wins else 0.0)
    equity = peak = initial_balance
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    sharpe = 0.0
    if len(returns) >= 2:
        deviation = statistics.pstdev(returns)
        sharpe = statistics.mean(returns) / deviation if deviation > 0 else 0.0
    return {
        "net_pnl": sum(pnls),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "trade_count": len(rows),
    }


def _is_router_trade(row) -> bool:
    strategy_id = str(_value(row, "strategy_id", ""))
    return (
        strategy_id.startswith("S")
        and strategy_id[1:].isdigit()
        and 20 <= int(strategy_id[1:]) <= 55
    )


def _load_rows(database_path: Path) -> list[dict]:
    if not database_path.exists():
        return []
    con = sqlite3.connect(database_path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in con.execute("SELECT * FROM tournament_trades WHERE source='PAPER' ORDER BY id")]
    finally:
        con.close()


def _group_metrics(rows: Iterable[dict], key: str) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return {name: _metrics(items, 1000.0) for name, items in grouped.items()}


def _candidate_rows(rows: list[dict], excluded_strategies: set[str], symbol_blacklist: set[str]) -> list[dict]:
    return [
        row for row in rows
        if row["strategy_id"] not in excluded_strategies and row["symbol"] not in symbol_blacklist
    ]


def _scenario_rows(rows: list[dict], scenario: str) -> list[dict]:
    output = [dict(row) for row in rows]
    if scenario == "baseline":
        return output
    if scenario == "fee_slippage_2x":
        for row in output:
            row["pnl"] = _as_float(row, "pnl") - _as_float(row, "fee") - _as_float(row, "slippage")
            row["return_pct"] = row["pnl"] / max(1.0, _as_float(row, "balance_before", 1000.0))
        return output
    if scenario == "pnl_haircut_25":
        for row in output:
            row["pnl"] = _as_float(row, "pnl") * (0.75 if _as_float(row, "pnl") > 0 else 1.25)
            row["return_pct"] = row["pnl"] / max(1.0, _as_float(row, "balance_before", 1000.0))
        return output
    if scenario == "remove_top_10pct_winners":
        winners = sorted((row for row in output if _as_float(row, "pnl") > 0), key=lambda item: _as_float(item, "pnl"), reverse=True)
        remove_count = max(1, int(len(winners) * 0.10)) if winners else 0
        removed = {id(row) for row in winners[:remove_count]}
        return [row for row in output if id(row) not in removed]
    if scenario == "loss_cluster":
        losses = [row for row in output if _as_float(row, "pnl") < 0]
        wins = [row for row in output if _as_float(row, "pnl") >= 0]
        return losses + wins
    return output


def _passes(metrics: dict) -> bool:
    return (
        metrics["trade_count"] >= MIN_LIVE_TRADES
        and metrics["net_pnl"] > 0
        and metrics["win_rate"] >= MIN_LIVE_WIN_RATE
        and metrics["profit_factor"] >= MIN_LIVE_PROFIT_FACTOR
        and metrics["max_drawdown"] <= MAX_LIVE_DRAWDOWN
    )


def _recommend_config(rows: list[dict]) -> dict:
    router_rows = [row for row in rows if _is_router_trade(row)]
    strategy_metrics = _group_metrics(router_rows, "strategy_id")
    symbol_metrics = _group_metrics(router_rows, "symbol")
    excluded = {
        strategy_id for strategy_id, metrics in strategy_metrics.items()
        if metrics["trade_count"] >= 10 and (metrics["profit_factor"] < 0.75 or metrics["net_pnl"] < -25)
    }
    excluded.add("S99")
    symbol_blacklist = {
        symbol for symbol, metrics in symbol_metrics.items()
        if metrics["trade_count"] >= 10 and (metrics["profit_factor"] < 0.50 or metrics["net_pnl"] < -20)
    }
    blocked_pairs = []
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in router_rows:
        grouped[(row["strategy_id"], row["symbol"], row["direction"])].append(row)
    for (strategy_id, symbol, direction), items in grouped.items():
        metrics = _metrics(items, 1000.0)
        if metrics["trade_count"] >= 3 and metrics["profit_factor"] < 0.80:
            blocked_pairs.append(f"{strategy_id}:{symbol}:{direction}")
    return {
        "strategy_id": "S99",
        "minimum_score": 70,
        "allowed_strategies": [],
        "excluded_strategies": sorted(excluded),
        "symbol_blacklist": sorted(symbol_blacklist),
        "blocked_pairs": sorted(blocked_pairs),
        "max_leverage": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "paper_trade_stress_analysis",
    }


def run_stress_test(settings: Settings, persist: bool = True) -> dict:
    rows = _load_rows(settings.database_path)
    router_rows = [row for row in rows if _is_router_trade(row)]
    config = _recommend_config(rows)
    candidate = _candidate_rows(router_rows, set(config["excluded_strategies"]), set(config["symbol_blacklist"]))
    scenarios = {}
    for name in ("baseline", "fee_slippage_2x", "pnl_haircut_25", "remove_top_10pct_winners", "loss_cluster"):
        scenarios[name] = _metrics(_scenario_rows(candidate, name), settings.initial_balance)
    live_ready = bool(candidate) and all(_passes(metrics) for metrics in scenarios.values())
    pnl_values = [_as_float(row, "pnl") for row in candidate]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": len(rows),
        "router_trade_count": len(router_rows),
        "candidate_trade_count": len(candidate),
        "live_ready": live_ready,
        "decision": "LOCK_S99" if live_ready else "PAPER_ONLY",
        "reason": (
            "candidate passed every stress scenario"
            if live_ready else "stress criteria not met; keep paper trading and collect more data"
        ),
        "observed": {
            "overall": _metrics(rows, settings.initial_balance),
            "router": _metrics(router_rows, settings.initial_balance),
            "by_strategy": _group_metrics(router_rows, "strategy_id"),
            "by_symbol": _group_metrics(router_rows, "symbol"),
            "pnl_stddev": statistics.pstdev(pnl_values) if len(pnl_values) >= 2 else 0.0,
        },
        "router_config": config,
        "scenarios": scenarios,
        "criteria": {
            "min_trades": MIN_LIVE_TRADES,
            "min_win_rate": MIN_LIVE_WIN_RATE,
            "min_profit_factor": MIN_LIVE_PROFIT_FACTOR,
            "max_drawdown": MAX_LIVE_DRAWDOWN,
        },
    }
    if persist:
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        (settings.config_dir / "router_config.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (settings.config_dir / "stress_test_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def summary_text(report: dict) -> str:
    scenario_lines = [
        f"{name}: {metrics['trade_count']} trades, PnL {metrics['net_pnl']:+.2f}, "
        f"WR {metrics['win_rate'] * 100:.1f}%, PF {metrics['profit_factor']:.2f}, "
        f"MDD {metrics['max_drawdown'] * 100:.1f}%"
        for name, metrics in report["scenarios"].items()
    ]
    return "\n".join([
        "STRESS_TEST_REPORT",
        f"generated_at: {report['generated_at']}",
        f"decision: {report['decision']}",
        f"live_ready: {report['live_ready']}",
        f"reason: {report['reason']}",
        f"total_trades: {report['trade_count']}",
        f"router_trades: {report['router_trade_count']}",
        f"candidate_trades: {report['candidate_trade_count']}",
        *scenario_lines,
    ])


def main() -> None:
    settings = Settings.from_env()
    report = run_stress_test(settings, persist=True)
    print(summary_text(report))


if __name__ == "__main__":
    main()
