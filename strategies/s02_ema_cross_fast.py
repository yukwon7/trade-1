from __future__ import annotations

from indicators import ema
from strategies.base import BaseStrategy
from strategies.utils import closes, sma


class EmaCrossFastStrategy(BaseStrategy):
    strategy_id = "S02"
    name = "EMA_CROSS_FAST"
    leverage = 7
    stop_loss_pct = 0.012

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        values = closes(candles_5m)
        if len(values) < self.minimum_candles:
            return None
        fast, slow = ema(values, 9), ema(values, 21)
        volume_average = sma([item.volume for item in candles_5m], 20)[-1]
        if candles_5m[-1].volume < volume_average:
            return None
        if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
            return self.signal(symbol, "LONG", values[-1], "EMA9 bullish cross + volume confirmation")
        if fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
            return self.signal(symbol, "SHORT", values[-1], "EMA9 bearish cross + volume confirmation")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        values = closes(candles_5m)
        fast, slow = ema(values, 9), ema(values, 21)
        if position.direction == "LONG" and fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
            return "EMA_REVERSE_CROSS"
        if position.direction == "SHORT" and fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
            return "EMA_REVERSE_CROSS"
        return None
