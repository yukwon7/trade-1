from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import bollinger, closes, rsi_values


class MeanReversionBbStrategy(BaseStrategy):
    strategy_id = "S08"
    name = "MEAN_REVERSION_BB"
    leverage = 5
    stop_loss_pct = 0.01

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        values = closes(candles_5m)
        if len(values) < self.minimum_candles:
            return None
        _, upper, lower, _ = bollinger(values)
        rsi = rsi_values(candles_5m)[-1]
        if candles_5m[-1].high >= upper[-1] and rsi > 70:
            return self.signal(symbol, "SHORT", values[-1], "upper BB outside touch + RSI overbought")
        if candles_5m[-1].low <= lower[-1] and rsi < 30:
            return self.signal(symbol, "LONG", values[-1], "lower BB outside touch + RSI oversold")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        middle, _, _, _ = bollinger(closes(candles_5m))
        if position.direction == "LONG" and candles_5m[-1].high >= middle[-1]:
            return "BB_MIDDLE_REACHED"
        if position.direction == "SHORT" and candles_5m[-1].low <= middle[-1]:
            return "BB_MIDDLE_REACHED"
        return None
