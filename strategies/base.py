from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from models import Candle, Direction, StrategySignal, TournamentPosition


class BaseStrategy:
    strategy_id = ""
    name = ""
    leverage = 1
    stop_loss_pct = 0.01
    take_profit_pct: float | None = None
    minimum_candles = 60

    def evaluate(
        self,
        symbol: str,
        candles_5m: Sequence[Candle],
        candles_15m: Sequence[Candle],
        context: dict[str, Any] | None = None,
    ) -> StrategySignal | None:
        raise NotImplementedError

    def should_exit(
        self,
        position: TournamentPosition,
        candles_5m: Sequence[Candle],
        candles_15m: Sequence[Candle],
        context: dict[str, Any] | None = None,
    ) -> str | None:
        raise NotImplementedError

    def signal(self, symbol: str, direction: Direction, price: float, reason: str, metadata=None) -> StrategySignal:
        return StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.name,
            symbol=symbol,
            direction=direction,
            entry_price=price,
            leverage=self.leverage,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            reason=reason,
            metadata=metadata or {},
        )
