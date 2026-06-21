from __future__ import annotations

from models import PositionState


class PyramidManager:
    FRACTIONS = (0.25, 0.20, 0.15)

    @classmethod
    def next_add_size(cls, position: PositionState, price: float, trend_valid: bool) -> float:
        if not trend_valid or position.add_count >= 3:
            return 0.0
        profitable = price > position.entry_price if position.direction == "LONG" else price < position.entry_price
        anchor = position.last_add_price or position.entry_price
        distance_ok = (
            price >= anchor + position.initial_atr * 0.5
            if position.direction == "LONG"
            else price <= anchor - position.initial_atr * 0.5
        )
        if not profitable or not distance_ok:
            return 0.0
        return position.initial_size * cls.FRACTIONS[position.add_count] / 0.40
