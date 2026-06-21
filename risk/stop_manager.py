from __future__ import annotations

from models import ExitEvent, PositionState


class StopManager:
    @staticmethod
    def initial_levels(direction: str, entry: float, atr: float) -> tuple[float, float]:
        risk = atr * 1.5
        if direction == "LONG":
            return entry - risk, entry + atr * 3.0
        return entry + risk, entry - atr * 3.0

    @staticmethod
    def update(position: PositionState, high: float, low: float, close: float) -> ExitEvent | None:
        position.current_price = close
        # When both extremes occur in one candle their order is unknown. Honor the
        # stop that existed at candle-open before moving it or taking profit.
        if position.direction == "LONG" and low <= position.sl_price:
            reason = "TRAILING_STOP" if position.trailing_active else "BREAK_EVEN" if position.sl_price >= position.entry_price else "STOP_LOSS"
            return ExitEvent(position.symbol, position.direction, position.sl_price, position.remaining_size, reason, True)
        if position.direction == "SHORT" and high >= position.sl_price:
            reason = "TRAILING_STOP" if position.trailing_active else "BREAK_EVEN" if position.sl_price <= position.entry_price else "STOP_LOSS"
            return ExitEvent(position.symbol, position.direction, position.sl_price, position.remaining_size, reason, True)
        position.highest_price = max(position.highest_price or position.entry_price, high)
        position.lowest_price = min(position.lowest_price or position.entry_price, low)
        one_r = position.one_r

        if position.direction == "LONG":
            if position.highest_price >= position.entry_price + one_r:
                position.sl_price = max(position.sl_price, position.entry_price)
            if not position.trailing_active and high >= position.tp_price:
                position.trailing_active = True
                position.sl_price = max(position.sl_price, high - position.initial_atr)
                return ExitEvent(position.symbol, position.direction, position.tp_price, position.remaining_size * 0.5, "TAKE_PROFIT_2R", False)
            if position.trailing_active:
                position.sl_price = max(position.sl_price, position.highest_price - position.initial_atr)
        else:
            if position.lowest_price <= position.entry_price - one_r:
                position.sl_price = min(position.sl_price, position.entry_price)
            if not position.trailing_active and low <= position.tp_price:
                position.trailing_active = True
                position.sl_price = min(position.sl_price, low + position.initial_atr)
                return ExitEvent(position.symbol, position.direction, position.tp_price, position.remaining_size * 0.5, "TAKE_PROFIT_2R", False)
            if position.trailing_active:
                position.sl_price = min(position.sl_price, position.lowest_price + position.initial_atr)
        return None
