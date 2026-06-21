from __future__ import annotations

from models import PositionState, Signal
from risk.stop_manager import StopManager


def new_position(signal: Signal, total_quantity: float, initial_fraction: float = 0.40) -> PositionState:
    initial_size = total_quantity * initial_fraction
    stop, target = StopManager.initial_levels(signal.direction, signal.entry_price, signal.atr)
    return PositionState(
        id=None,
        symbol=signal.symbol,
        direction=signal.direction,
        entry_price=signal.entry_price,
        current_price=signal.entry_price,
        size=initial_size,
        remaining_size=initial_size,
        initial_size=initial_size,
        initial_atr=signal.atr,
        leverage=signal.leverage,
        score=signal.score,
        last_add_price=signal.entry_price,
        sl_price=stop,
        tp_price=target,
        highest_price=signal.entry_price,
        lowest_price=signal.entry_price,
    )
