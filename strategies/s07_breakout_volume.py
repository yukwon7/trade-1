from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import sma


class BreakoutVolumeStrategy(BaseStrategy):
    strategy_id = "S07"
    name = "BREAKOUT_VOLUME"
    leverage = 7
    stop_loss_pct = 0.01
    take_profit_pct = 0.015

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if len(candles_5m) < self.minimum_candles:
            return None
        prior = candles_5m[-21:-1]
        high, low = max(item.high for item in prior), min(item.low for item in prior)
        volume_average = sma([item.volume for item in candles_5m[:-1]], 20)[-1]
        last = candles_5m[-1]
        if last.volume <= volume_average * 2:
            return None
        if last.close > high:
            return self.signal(symbol, "LONG", last.close, "20-candle high breakout + volume 2x", {"breakout_level": high})
        if last.close < low:
            return self.signal(symbol, "SHORT", last.close, "20-candle low breakout + volume 2x", {"breakout_level": low})
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        level = float(position.metadata.get("breakout_level", position.entry_price))
        if position.direction == "LONG" and candles_5m[-1].close <= level:
            return "BREAKOUT_LEVEL_RETURN"
        if position.direction == "SHORT" and candles_5m[-1].close >= level:
            return "BREAKOUT_LEVEL_RETURN"
        return None
