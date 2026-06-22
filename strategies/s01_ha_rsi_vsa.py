from __future__ import annotations

from strategies.base import BaseStrategy
from strategies.utils import heikin_ashi, rsi_values


class HARsiVsaStrategy(BaseStrategy):
    strategy_id = "S01"
    name = "HA_RSI_VSA"
    leverage = 5
    stop_loss_pct = 0.01

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if len(candles_5m) < self.minimum_candles:
            return None
        ha_open, ha_close = heikin_ashi(candles_5m)
        values = rsi_values(candles_5m)
        volume_ok = candles_5m[-1].volume > candles_5m[-2].volume * 1.5
        if ha_close[-2] <= ha_open[-2] and ha_close[-1] > ha_open[-1] and values[-2] <= 50 < values[-1] and volume_ok:
            return self.signal(symbol, "LONG", candles_5m[-1].close, "HA bullish reversal + RSI50 cross + volume 1.5x")
        if ha_close[-2] >= ha_open[-2] and ha_close[-1] < ha_open[-1] and values[-2] >= 50 > values[-1] and volume_ok:
            return self.signal(symbol, "SHORT", candles_5m[-1].close, "HA bearish reversal + RSI50 cross + volume 1.5x")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        ha_open, ha_close = heikin_ashi(candles_5m)
        values = rsi_values(candles_5m)
        if position.direction == "LONG":
            if all(ha_close[index] < ha_open[index] for index in (-2, -1)):
                return "HA_TWO_BEARISH"
            if values[-2] >= 50 > values[-1]:
                return "RSI_REVERSE_CROSS"
        else:
            if all(ha_close[index] > ha_open[index] for index in (-2, -1)):
                return "HA_TWO_BULLISH"
            if values[-2] <= 50 < values[-1]:
                return "RSI_REVERSE_CROSS"
        return None
