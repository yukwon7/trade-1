from __future__ import annotations

from models import TournamentPosition


def summarize_positions(positions: dict[str, TournamentPosition]) -> list[dict]:
    output = []
    for position in sorted(positions.values(), key=lambda item: item.symbol):
        gross = (
            (position.current_price - position.entry_price) * position.size
            if position.direction == "LONG"
            else (position.entry_price - position.current_price) * position.size
        )
        output.append({
            "symbol": position.symbol,
            "strategy_id": position.strategy_id,
            "direction": position.direction,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "leverage": position.leverage,
            "unrealized_gross": gross,
            "stop_price": position.stop_price,
            "take_profit_price": position.take_profit_price,
        })
    return output
