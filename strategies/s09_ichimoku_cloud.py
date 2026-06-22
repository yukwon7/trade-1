from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import ichimoku_cloud


class IchimokuCloudStrategy(BaseStrategy):
    strategy_id = "S09"
    name = "ICHIMOKU_CLOUD"
    leverage = 4
    stop_loss_pct = 0.015
    minimum_candles = 90

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if len(candles_5m) < self.minimum_candles:
            return None
        conversion, base, cloud_low, cloud_high = ichimoku_cloud(candles_5m, -1)
        _, _, previous_low, previous_high = ichimoku_cloud(candles_5m, -2)
        current, previous = candles_5m[-1].close, candles_5m[-2].close
        if previous <= previous_high and current > cloud_high and conversion > base:
            return self.signal(symbol, "LONG", current, "bullish cloud breakout + conversion above base")
        if previous >= previous_low and current < cloud_low and conversion < base:
            return self.signal(symbol, "SHORT", current, "bearish cloud breakout + conversion below base")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        _, _, cloud_low, cloud_high = ichimoku_cloud(candles_5m, -1)
        current = candles_5m[-1].close
        if position.direction == "LONG" and current <= cloud_high:
            return "CLOUD_REENTRY"
        if position.direction == "SHORT" and current >= cloud_low:
            return "CLOUD_REENTRY"
        return None
