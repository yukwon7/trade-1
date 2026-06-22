from __future__ import annotations

from strategies.base import BaseStrategy


class OrderImbalanceScalpStrategy(BaseStrategy):
    strategy_id = "S04"
    name = "ORDER_IMBALANCE_SCALP"
    leverage = 10
    stop_loss_pct = 0.002
    take_profit_pct = 0.004

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        context = context or {}
        bids, asks = context.get("bids", []), context.get("asks", [])
        price = float(context.get("mark_price", candles_5m[-1].close))
        if not bids or not asks or len(candles_5m) < 2:
            return None
        bid_quantity = sum(float(row[1]) for row in bids[:20])
        ask_quantity = sum(float(row[1]) for row in asks[:20])
        move = price / candles_5m[-2].close - 1.0
        if ask_quantity > 0 and bid_quantity / ask_quantity >= 2.5 and move >= 0.001:
            return self.signal(symbol, "LONG", price, "bid/ask imbalance >=2.5 + upward move 0.1%")
        if bid_quantity > 0 and ask_quantity / bid_quantity >= 2.5 and move <= -0.001:
            return self.signal(symbol, "SHORT", price, "ask/bid imbalance >=2.5 + downward move 0.1%")
        return None

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        return None
