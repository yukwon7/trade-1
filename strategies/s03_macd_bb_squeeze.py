from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import bollinger, closes, macd


class MacdBbSqueezeStrategy(BaseStrategy):
    strategy_id = "S03"
    name = "MACD_BB_SQUEEZE"
    leverage = 5
    stop_loss_pct = 0.01

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        values = closes(candles_5m)
        if len(values) < self.minimum_candles:
            return None
        _, _, _, width = bollinger(values)
        _, _, histogram = macd(values)
        squeezed = width[-2] <= min(width[-22:-2]) and width[-1] > width[-2]
        if not squeezed:
            return None
        if histogram[-1] > 0 and histogram[-1] > histogram[-2]:
            return self.signal(symbol, "LONG", values[-1], "BB squeeze expansion + positive MACD histogram")
        if histogram[-1] < 0 and histogram[-1] < histogram[-2]:
            return self.signal(symbol, "SHORT", values[-1], "BB squeeze expansion + negative MACD histogram")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        values = closes(candles_5m)
        _, upper, lower, _ = bollinger(values)
        _, _, histogram = macd(values)
        if position.direction == "LONG" and (candles_5m[-1].low <= lower[-1] or histogram[-1] < 0):
            return "OPPOSITE_BAND_OR_MACD"
        if position.direction == "SHORT" and (candles_5m[-1].high >= upper[-1] or histogram[-1] > 0):
            return "OPPOSITE_BAND_OR_MACD"
        return None
