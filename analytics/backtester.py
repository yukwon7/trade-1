from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import aiohttp

from config import Settings
from exchange import BinanceFuturesClient
from risk import StopManager, leverage_for_score
from strategy import SignalEngine
from trader.position import new_position


class Backtester:
    def __init__(self, fee_rate: float, slippage: float):
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.engine = SignalEngine()

    def run(self, symbol: str, one_hour, fifteen, five, minimum_score: int, max_leverage: int) -> dict:
        position = None
        pnl_values: list[float] = []
        by_time_1h = {item.open_time: index for index, item in enumerate(one_hour)}
        by_time_15m = {item.open_time: index for index, item in enumerate(fifteen)}
        for index in range(60, len(five)):
            candle = five[index]
            # Use only higher-timeframe candles that were fully closed when this
            # 5M candle completed. This avoids multi-timeframe lookahead bias.
            hour_key = candle.open_time - candle.open_time % 3_600_000 - 3_600_000
            fifteen_key = candle.open_time - candle.open_time % 900_000 - 900_000
            hour_index = by_time_1h.get(hour_key)
            fifteen_index = by_time_15m.get(fifteen_key)
            if hour_index is None or fifteen_index is None or hour_index < 59 or fifteen_index < 59:
                continue
            if position:
                event = StopManager.update(position, candle.high, candle.low, candle.close)
                if event:
                    gross = (event.price - position.entry_price) * event.size if position.direction == "LONG" else (position.entry_price - event.price) * event.size
                    cost = (position.entry_price + event.price) * event.size * self.fee_rate + position.entry_price * event.size * self.slippage
                    position.realized_pnl += gross - cost
                    position.remaining_size -= event.size
                    if event.final:
                        pnl_values.append(position.realized_pnl)
                        position = None
            if position is None:
                signal, _ = self.engine.analyze(
                    symbol,
                    one_hour[max(0, hour_index - 499) : hour_index + 1],
                    fifteen[max(0, fifteen_index - 499) : fifteen_index + 1],
                    five[max(0, index - 499) : index + 1],
                    minimum_score,
                )
                if signal:
                    leverage = leverage_for_score(signal.score, max_leverage)
                    signal = replace(signal, leverage=leverage)
                    risk_distance = signal.atr * 1.5
                    quantity = 10.0 / risk_distance if risk_distance > 0 else 0
                    position = new_position(signal, quantity)
        wins = sum(1 for value in pnl_values if value > 0)
        return {"symbol": symbol, "trades": len(pnl_values), "win_rate": wins / len(pnl_values) if pnl_values else 0, "pnl": sum(pnl_values)}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    settings = Settings.from_env()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    async with aiohttp.ClientSession() as session:
        client = BinanceFuturesClient(session, settings.binance_base_url, settings.binance_api_key)
        data = await asyncio.gather(*(
            client.get_historical_klines(args.symbol, timeframe, int(start.timestamp() * 1000), int(end.timestamp() * 1000))
            for timeframe in ("1h", "15m", "5m")
        ))
    print(Backtester(settings.fee_rate, settings.slippage).run(args.symbol, *data, settings.min_score, settings.max_leverage))


if __name__ == "__main__":
    asyncio.run(main())
