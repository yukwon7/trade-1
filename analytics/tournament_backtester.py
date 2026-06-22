from __future__ import annotations

import argparse
import asyncio
import bisect
import json
from datetime import datetime, timedelta, timezone

import aiohttp

from analytics.tournament_evaluator import _metrics
from config import Settings
from exchange import BinanceFuturesClient
from models import TournamentPosition
from strategies import STRATEGIES


class TournamentBacktester:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run_strategy(self, strategy, symbol: str, candles_5m, candles_15m) -> dict:
        if strategy.strategy_id in {"S04", "S06"}:
            return {"strategy_id": strategy.strategy_id, "symbol": symbol, "status": "LIVE_ONLY", "trades": []}
        balance = self.settings.initial_balance
        position = None
        trades = []
        fifteen_times = [item.open_time for item in candles_15m]
        for index in range(max(100, strategy.minimum_candles), len(candles_5m)):
            candle = candles_5m[index]
            five = candles_5m[max(0, index - 119) : index + 1]
            fifteen_end = bisect.bisect_right(fifteen_times, candle.open_time)
            fifteen = candles_15m[max(0, fifteen_end - 120) : fifteen_end]
            if len(fifteen) < 100:
                continue
            if position:
                reason, exit_price = self._fixed_exit(position, candle)
                if not reason:
                    reason = strategy.should_exit(position, five, fifteen, {})
                    exit_price = candle.close
                if reason:
                    pnl = self._pnl(position, exit_price)
                    trades.append({"pnl": pnl, "return_pct": pnl / position.balance_before})
                    balance += pnl
                    position = None
            if position is None:
                signal = strategy.evaluate(symbol, five, fifteen, {})
                if signal:
                    stop = signal.entry_price * (1 - signal.stop_loss_pct if signal.direction == "LONG" else 1 + signal.stop_loss_pct)
                    target = None
                    if signal.take_profit_pct:
                        target = signal.entry_price * (1 + signal.take_profit_pct if signal.direction == "LONG" else 1 - signal.take_profit_pct)
                    loss_per_unit = (
                        abs(signal.entry_price - stop)
                        + signal.entry_price * (self.settings.fee_rate + self.settings.slippage)
                        + stop * self.settings.fee_rate
                    )
                    risk_quantity = balance * self.settings.risk_per_trade / loss_per_unit
                    margin_quantity = (balance / self.settings.max_open_positions) * signal.leverage / signal.entry_price
                    quantity = min(risk_quantity, margin_quantity)
                    position = TournamentPosition(
                        id=None, symbol=symbol, strategy_id=signal.strategy_id, strategy_name=signal.strategy_name,
                        direction=signal.direction, entry_price=signal.entry_price, current_price=signal.entry_price,
                        size=quantity, leverage=signal.leverage, stop_price=stop, take_profit_price=target,
                        balance_before=balance, metadata=signal.metadata,
                        fee_paid=signal.entry_price * quantity * self.settings.fee_rate,
                        slippage_paid=signal.entry_price * quantity * self.settings.slippage,
                    )
        return {"strategy_id": strategy.strategy_id, "symbol": symbol, "status": "OK", "trades": trades}

    @staticmethod
    def _fixed_exit(position, candle):
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

    def _pnl(self, position, exit_price):
        gross = (
            (exit_price - position.entry_price) * position.size
            if position.direction == "LONG" else (position.entry_price - exit_price) * position.size
        )
        fees = position.fee_paid + exit_price * position.size * self.settings.fee_rate
        return gross - fees - position.slippage_paid


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    settings = Settings.from_env()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(7, args.days))
    async with aiohttp.ClientSession() as session:
        client = BinanceFuturesClient(session, settings.binance_base_url, settings.binance_api_key)
        data = {}
        for symbol in settings.symbols:
            data[symbol] = await asyncio.gather(*(
                client.get_historical_klines(symbol, timeframe, int(start.timestamp() * 1000), int(end.timestamp() * 1000))
                for timeframe in ("5m", "15m")
            ))
    runner = TournamentBacktester(settings)
    detail = [
        runner.run_strategy(strategy, symbol, *data[symbol])
        for strategy in STRATEGIES.values() for symbol in settings.symbols
    ]
    rankings = []
    for strategy_id in STRATEGIES:
        rows = [trade for item in detail if item["strategy_id"] == strategy_id for trade in item["trades"]]
        rankings.append({"strategy_id": strategy_id, **_metrics(rows, settings.initial_balance * len(settings.symbols))})
    output = {"generated_at": end.isoformat(), "days": args.days, "rankings": rankings, "detail": detail}
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "tournament_backtest.json"
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"generated_at": output["generated_at"], "rankings": rankings}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
