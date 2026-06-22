from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Direction = Literal["LONG", "SHORT"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True, frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0


@dataclass(slots=True, frozen=True)
class StrategySignal:
    strategy_id: str
    strategy_name: str
    symbol: str
    direction: Direction
    entry_price: float
    leverage: int
    stop_loss_pct: float
    take_profit_pct: float | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class TournamentPosition:
    id: int | None
    symbol: str
    strategy_id: str
    strategy_name: str
    direction: Direction
    entry_price: float
    current_price: float
    size: float
    leverage: int
    stop_price: float
    take_profit_price: float | None
    balance_before: float
    metadata: dict[str, Any] = field(default_factory=dict)
    fee_paid: float = 0.0
    slippage_paid: float = 0.0
    status: str = "OPEN"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def margin(self) -> float:
        return self.current_price * self.size / self.leverage
