from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import rolling_vwap


class VwapRevertStrategy(BaseStrategy):
    strategy_id = "S10"
    name = "VWAP_REVERT"
    leverage = 6
    stop_loss_pct = 0.008
    minimum_candles = 100

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if len(candles_5m) < self.minimum_candles:
            return None
        vwap = rolling_vwap(candles_5m)
        previous_deviation = candles_5m[-2].close / vwap[-2] - 1.0
        current_deviation = candles_5m[-1].close / vwap[-1] - 1.0
        if previous_deviation <= -0.015 and current_deviation > previous_deviation:
            return self.signal(symbol, "LONG", candles_5m[-1].close, "VWAP -1.5% deviation starts reverting", {"vwap": vwap[-1]})
        if previous_deviation >= 0.015 and current_deviation < previous_deviation:
            return self.signal(symbol, "SHORT", candles_5m[-1].close, "VWAP +1.5% deviation starts reverting", {"vwap": vwap[-1]})
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        vwap = rolling_vwap(candles_5m)[-1]
        if position.direction == "LONG" and candles_5m[-1].high >= vwap:
            return "VWAP_REACHED"
        if position.direction == "SHORT" and candles_5m[-1].low <= vwap:
            return "VWAP_REACHED"
        return None
