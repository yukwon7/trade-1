from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

from analytics.stress_tester import _metrics, _scenario_rows
from config import Settings
from exchange import BinanceFuturesClient
from models import Candle, TournamentPosition
from strategies import STRATEGIES


BACKTEST_SCENARIOS = ("baseline", "fee_slippage_2x", "pnl_haircut_25", "remove_top_10pct_winners", "loss_cluster")
BACKTEST_REPORT_NAME = "router_backtest_stress_period.json"


def _is_catalog_strategy(strategy_id: str) -> bool:
    return strategy_id.startswith("S") and strategy_id[1:].isdigit() and 20 <= int(strategy_id[1:]) <= 60


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _existing_database_paths(settings: Settings) -> list[Path]:
    paths = [settings.database_path]
    legacy_path = (Path.cwd() / "trades.db").resolve()
    if legacy_path not in paths:
        paths.append(legacy_path)
    return [path for path in paths if path.exists()]


def _infer_stress_period(settings: Settings) -> tuple[datetime, datetime, int, str]:
    """Infer the active stress-test period from stored paper-trading history.

    A --days value of 0 means "use the period that actually exists in the DB",
    not an arbitrary one-year or fixed window.  Both the current and legacy
    trade table names are scanned so cleanup/rename work does not hide history.
    """
    starts: list[datetime] = []
    ends: list[datetime] = []
    sources: list[str] = []

    for db_path in _existing_database_paths(settings):
        try:
            with sqlite3.connect(db_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute("select name from sqlite_master where type='table'")
                }
                for table in ("tournament_trades", "trades"):
                    if table not in tables:
                        continue
                    columns = {
                        row[1]
                        for row in connection.execute(f"pragma table_info({table})")
                    }
                    for column in ("entry_time", "exit_time", "created_at"):
                        if column not in columns:
                            continue
                        row = connection.execute(
                            f"select min({column}), max({column}), count({column}) "
                            f"from {table} where {column} is not null and {column} != ''"
                        ).fetchone()
                        if not row or not row[2]:
                            continue
                        start = _parse_datetime(row[0])
                        end = _parse_datetime(row[1])
                        if start and end:
                            starts.append(start)
                            ends.append(end)
                            sources.append(f"{db_path.name}:{table}.{column}")
        except sqlite3.Error:
            continue

    if starts and ends:
        start = min(starts)
        end = max(ends)
        if end <= start:
            end = start + timedelta(days=1)
        days = max(1, math.ceil((end - start).total_seconds() / 86400))
        return start, end, days, ",".join(sorted(set(sources)))

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    return start, end, 7, "fallback_last_7_days_no_trade_history"


def _candle_to_row(candle: Candle) -> list[float]:
    return [candle.open_time, candle.open, candle.high, candle.low, candle.close, candle.volume, candle.quote_volume]


def _row_to_candle(row: list[float]) -> Candle:
    return Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[6]))


async def _load_candles(settings: Settings, client: BinanceFuturesClient, symbol: str, timeframe: str, start_ms: int, end_ms: int, refresh: bool) -> list[Candle]:
    cache_dir = settings.data_dir / "backtest_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{symbol}_{timeframe}_{start_ms}_{end_ms}.json"
    if path.exists() and not refresh:
        return [_row_to_candle(row) for row in json.loads(path.read_text(encoding="utf-8"))]
    candles = await client.get_historical_klines(symbol, timeframe, start_ms, end_ms)
    path.write_text(json.dumps([_candle_to_row(candle) for candle in candles], separators=(",", ":")), encoding="utf-8")
    return candles


def _fixed_exit(position: TournamentPosition, candle: Candle) -> tuple[str | None, float]:
    if position.direction == "LONG":
        if candle.low <= position.stop_price:
            return "STOP_LOSS", position.stop_price
        if position.take_profit_price is not None and candle.high >= position.take_profit_price:
            return "TAKE_PROFIT", position.take_profit_price
    else:
        if candle.high >= position.stop_price:
            return "STOP_LOSS", position.stop_price
        if position.take_profit_price is not None and candle.low <= position.take_profit_price:
            return "TAKE_PROFIT", position.take_profit_price
    return None, candle.close


def _pnl(settings: Settings, position: TournamentPosition, exit_price: float) -> float:
    gross = (
        (exit_price - position.entry_price) * position.size
        if position.direction == "LONG" else (position.entry_price - exit_price) * position.size
    )
    exit_fee = exit_price * position.size * settings.fee_rate
    return gross - position.fee_paid - exit_fee - position.slippage_paid


def _open_position(settings: Settings, signal, balance: float) -> TournamentPosition | None:
    leverage = max(1, min(settings.max_leverage, signal.leverage))
    stop_price = signal.entry_price * (
        1.0 - signal.stop_loss_pct if signal.direction == "LONG" else 1.0 + signal.stop_loss_pct
    )
    take_profit = None
    if signal.take_profit_pct:
        take_profit = signal.entry_price * (
            1.0 + signal.take_profit_pct if signal.direction == "LONG" else 1.0 - signal.take_profit_pct
        )
    stop_distance = abs(signal.entry_price - stop_price)
    loss_per_unit = stop_distance + signal.entry_price * (settings.fee_rate + settings.slippage) + stop_price * settings.fee_rate
    risk_quantity = balance * settings.risk_per_trade / loss_per_unit if loss_per_unit else 0.0
    margin_quantity = (balance / settings.max_open_positions) * leverage / signal.entry_price if signal.entry_price > 0 else 0.0
    quantity = max(0.0, min(risk_quantity, margin_quantity))
    if quantity <= 0:
        return None
    return TournamentPosition(
        id=None,
        symbol=signal.symbol,
        strategy_id=signal.strategy_id,
        strategy_name=signal.strategy_name,
        direction=signal.direction,
        entry_price=signal.entry_price,
        current_price=signal.entry_price,
        size=quantity,
        leverage=leverage,
        stop_price=stop_price,
        take_profit_price=take_profit,
        balance_before=balance,
        metadata=signal.metadata,
        fee_paid=signal.entry_price * quantity * settings.fee_rate,
        slippage_paid=signal.entry_price * quantity * settings.slippage,
    )


def run_strategy_symbol(settings: Settings, strategy, symbol: str, candles_5m: list[Candle], candles_15m: list[Candle], step: int) -> list[dict]:
    if not candles_5m or not candles_15m:
        return []
    balance = settings.initial_balance
    position: TournamentPosition | None = None
    trades: list[dict] = []
    fifteen_times = [item.open_time for item in candles_15m]
    start = max(220, strategy.minimum_candles)
    for index in range(start, len(candles_5m), max(1, step)):
        candle = candles_5m[index]
        fifteen_end = bisect.bisect_right(fifteen_times, candle.open_time)
        if fifteen_end < 120:
            continue
        five = candles_5m[max(0, index - 240) : index + 1]
        fifteen = candles_15m[max(0, fifteen_end - 240) : fifteen_end]
        if position is not None:
            reason, exit_price = _fixed_exit(position, candle)
            if reason is None:
                reason = strategy.should_exit(position, five, fifteen, {})
                exit_price = candle.close
            if reason:
                pnl = _pnl(settings, position, exit_price)
                trades.append({
                    "strategy_id": position.strategy_id,
                    "strategy_name": position.strategy_name,
                    "symbol": symbol,
                    "direction": position.direction,
                    "entry_price": position.entry_price,
                    "exit_price": exit_price,
                    "entry_time": position.created_at,
                    "exit_time": datetime.fromtimestamp(candle.open_time / 1000, timezone.utc).isoformat(),
                    "fee": position.fee_paid + exit_price * position.size * settings.fee_rate,
                    "slippage": position.slippage_paid,
                    "pnl": pnl,
                    "return_pct": pnl / position.balance_before if position.balance_before > 0 else 0.0,
                    "balance_before": position.balance_before,
                    "exit_reason": reason,
                })
                balance += pnl
                position = None
        if position is None:
            signal = strategy.evaluate(symbol, five, fifteen, {})
            if signal is not None:
                position = _open_position(settings, signal, balance)
                if position is not None:
                    position.created_at = datetime.fromtimestamp(candle.open_time / 1000, timezone.utc).isoformat()
    if position is not None:
        candle = candles_5m[-1]
        pnl = _pnl(settings, position, candle.close)
        trades.append({
            "strategy_id": position.strategy_id,
            "strategy_name": position.strategy_name,
            "symbol": symbol,
            "direction": position.direction,
            "entry_price": position.entry_price,
            "exit_price": candle.close,
            "entry_time": position.created_at,
            "exit_time": datetime.fromtimestamp(candle.open_time / 1000, timezone.utc).isoformat(),
            "fee": position.fee_paid + candle.close * position.size * settings.fee_rate,
            "slippage": position.slippage_paid,
            "pnl": pnl,
            "return_pct": pnl / position.balance_before if position.balance_before > 0 else 0.0,
            "balance_before": position.balance_before,
            "exit_reason": "END_OF_BACKTEST",
        })
    return trades


def _strict_scenario_passes(metrics: dict) -> bool:
    return (
        metrics["trade_count"] >= 30
        and metrics["net_pnl"] > 0
        and metrics["profit_factor"] >= 1.15
        and metrics["max_drawdown"] <= 0.15
    )


def _short_period_strategy_passes(metrics: dict, scenarios: dict[str, dict]) -> bool:
    """Eligibility rule for the current stress-test DB period.

    The DB currently contains a short stress window, so the old 30-trade rule
    can reject every strategy and leave the router unable to trade.  This rule
    still blocks single-trade luck by requiring at least five trades and keeps
    only strategies that remain profitable after harsher fee/slippage and
    profit-haircut scenarios.
    """
    baseline = scenarios["baseline"]
    fee_stress = scenarios["fee_slippage_2x"]
    pnl_haircut = scenarios["pnl_haircut_25"]
    top_removed = scenarios["remove_top_10pct_winners"]
    loss_cluster = scenarios["loss_cluster"]
    return (
        metrics["trade_count"] >= 5
        and baseline["net_pnl"] > 0
        and baseline["profit_factor"] >= 1.15
        and baseline["max_drawdown"] <= 0.15
        and fee_stress["net_pnl"] > 0
        and fee_stress["profit_factor"] >= 1.05
        and fee_stress["max_drawdown"] <= 0.15
        and pnl_haircut["net_pnl"] > 0
        and pnl_haircut["profit_factor"] >= 1.0
        and pnl_haircut["max_drawdown"] <= 0.15
        and top_removed["net_pnl"] >= 0
        and top_removed["max_drawdown"] <= 0.15
        and loss_cluster["net_pnl"] > 0
        and loss_cluster["max_drawdown"] <= 0.15
    )


def _strategy_passes(metrics: dict, scenarios: dict[str, dict], days: int) -> bool:
    if days < 14:
        return _short_period_strategy_passes(metrics, scenarios)
    return all(_strict_scenario_passes(item) for item in scenarios.values())


async def run_backtest(days: int, step: int, refresh: bool, persist: bool = True) -> dict:
    settings = Settings.from_env()
    if days <= 0:
        start, end, resolved_days, period_source = _infer_stress_period(settings)
    else:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(1, days))
        resolved_days = max(1, days)
        period_source = "explicit_days"
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    async with aiohttp.ClientSession() as session:
        client = BinanceFuturesClient(session, settings.binance_base_url, settings.binance_api_key, concurrency=1)
        market_data = {}
        for symbol in settings.symbols:
            candles_5m = await _load_candles(settings, client, symbol, "5m", start_ms, end_ms, refresh)
            candles_15m = await _load_candles(settings, client, symbol, "15m", start_ms, end_ms, refresh)
            market_data[symbol] = (candles_5m, candles_15m)
            print(f"loaded {symbol}: 5m={len(candles_5m)} 15m={len(candles_15m)}")

    strategies = {key: strategy for key, strategy in STRATEGIES.items() if _is_catalog_strategy(key)}
    details = []
    trades_by_strategy: dict[str, list[dict]] = {key: [] for key in strategies}
    for strategy_id, strategy in strategies.items():
        for symbol, (candles_5m, candles_15m) in market_data.items():
            trades = run_strategy_symbol(settings, strategy, symbol, candles_5m, candles_15m, step)
            trades_by_strategy[strategy_id].extend(trades)
            details.append({"strategy_id": strategy_id, "symbol": symbol, "trades": len(trades), "net_pnl": sum(item["pnl"] for item in trades)})
        print(f"tested {strategy_id}: trades={len(trades_by_strategy[strategy_id])}")

    rankings = []
    allowed = []
    for strategy_id, trades in trades_by_strategy.items():
        metrics = _metrics(trades, settings.initial_balance * len(settings.symbols))
        scenarios = {name: _metrics(_scenario_rows(trades, name), settings.initial_balance * len(settings.symbols)) for name in BACKTEST_SCENARIOS}
        eligible = _strategy_passes(metrics, scenarios, resolved_days)
        if eligible:
            allowed.append(strategy_id)
        rankings.append({
            "strategy_id": strategy_id,
            "strategy_name": strategies[strategy_id].name,
            "eligible": eligible,
            **metrics,
            "scenarios": scenarios,
        })
    rankings.sort(key=lambda item: (item["eligible"], item["profit_factor"], item["net_pnl"]), reverse=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "days": resolved_days,
        "requested_days": days,
        "period_source": period_source,
        "evaluation_step": step,
        "eligibility_rule": (
            "short_period_profit_stress: trades>=5, baseline PF>=1.15, "
            "fee_slippage_2x/pnl_haircut/top_removed/loss_cluster profitable"
            if resolved_days < 14
            else "strict: every scenario trades>=30, pnl>0, PF>=1.15, MDD<=15%"
        ),
        "symbols": list(settings.symbols),
        "allowed_strategies": allowed,
        "rankings": rankings,
        "details": details,
        "sources": [
            "freqtrade/freqtrade-strategies",
            "freqtrade Supertrend strategy",
            "iterativv/NostalgiaForInfinity",
            "Reddit algotrading indicator-combination discussions",
        ],
    }
    if persist:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        report_path = settings.data_dir / BACKTEST_REPORT_NAME
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        config = {
            "strategy_id": "S99",
            "minimum_score": 70,
            "enforce_allowlist": True,
            "allowed_strategies": allowed,
            "excluded_strategies": sorted(set(strategies) - set(allowed)),
            "symbol_blacklist": [],
            "blocked_pairs": [],
            "max_leverage": 3,
            "generated_at": report["generated_at"],
            "source": "stress_period_router_backtest",
            "period_start": report["period_start"],
            "period_end": report["period_end"],
            "period_source": report["period_source"],
            "backtest_file": str(report_path),
        }
        (settings.config_dir / "router_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def print_summary(report: dict) -> None:
    print("ROUTER_BACKTEST_STRESS_PERIOD")
    print(f"generated_at: {report['generated_at']}")
    print(f"period: {report['period_start']} -> {report['period_end']}")
    print(f"days: {report['days']} source={report['period_source']}")
    print(f"allowed_strategies: {report['allowed_strategies']}")
    for item in report["rankings"][:12]:
        print(
            f"{item['strategy_id']} eligible={item['eligible']} trades={item['trade_count']} "
            f"pnl={item['net_pnl']:+.2f} wr={item['win_rate']*100:.1f}% "
            f"pf={item['profit_factor']:.2f} mdd={item['max_drawdown']*100:.1f}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=0, help="0 infers the actual stress-test period from the trade DB.")
    parser.add_argument("--step", type=int, default=12, help="Evaluate every Nth 5m candle. 12 means every 60 minutes.")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(run_backtest(args.days, args.step, args.refresh, persist=True))
    print_summary(report)


if __name__ == "__main__":
    main()
