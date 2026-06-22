from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import rsi_values


class RsiDivergenceStrategy(BaseStrategy):
    strategy_id = "S05"
    name = "RSI_DIVERGENCE"
    leverage = 5
    stop_loss_pct = 0.015

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if len(candles_5m) < self.minimum_candles:
            return None
        values = rsi_values(candles_5m)
        previous, recent = candles_5m[-20:-10], candles_5m[-10:]
        old_high = max(range(len(previous)), key=lambda i: previous[i].high)
        new_high = max(range(len(recent)), key=lambda i: recent[i].high)
        old_low = min(range(len(previous)), key=lambda i: previous[i].low)
        new_low = min(range(len(recent)), key=lambda i: recent[i].low)
        old_offset, new_offset = len(candles_5m) - 20, len(candles_5m) - 10
        if recent[new_high].high > previous[old_high].high and values[new_offset + new_high] < values[old_offset + old_high]:
            return self.signal(symbol, "SHORT", candles_5m[-1].close, "bearish RSI divergence")
        if recent[new_low].low < previous[old_low].low and values[new_offset + new_low] > values[old_offset + old_low]:
            return self.signal(symbol, "LONG", candles_5m[-1].close, "bullish RSI divergence")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        value = rsi_values(candles_5m)[-1]
        if position.direction == "LONG" and value >= 50:
            return "RSI_RETURN_50"
        if position.direction == "SHORT" and value <= 50:
            return "RSI_RETURN_50"
        return None
