from __future__ import annotations

from strategies.base import BaseStrategy


class FundingMomentumStrategy(BaseStrategy):
    strategy_id = "S06"
    name = "FUNDING_MOMENTUM"
    leverage = 3
    stop_loss_pct = 0.01
    take_profit_pct = 0.008

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        context = context or {}
        funding = float(context.get("funding_rate", 0.0))
        price = float(context.get("mark_price", candles_5m[-1].close))
        if abs(funding) <= 0.0001 or len(candles_5m) < 2:
            return None
        move = price / candles_5m[-2].close - 1.0
        metadata = {"next_funding_time": int(context.get("next_funding_time", 0))}
        if funding > 0 and move <= -0.003:
            return self.signal(symbol, "SHORT", price, "positive funding + opposite price move 0.3%", metadata)
        if funding < 0 and move >= 0.003:
            return self.signal(symbol, "LONG", price, "negative funding + opposite price move 0.3%", metadata)
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        next_funding = int(position.metadata.get("next_funding_time", 0))
        if next_funding and candles_5m[-1].open_time >= next_funding:
            return "NEXT_FUNDING_TIME"
        return None
