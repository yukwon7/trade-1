from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

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
class IndicatorSnapshot:
    symbol: str
    timeframe: str
    close: float
    ema20: float
    ema50: float
    rsi: float
    adx: float
    atr: float
    atr_average: float
    volume_ratio: float
    support: float
    resistance: float
    previous_close: float
    candle_high: float
    candle_low: float
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True, frozen=True)
class Signal:
    symbol: str
    direction: Direction
    score: int
    trend_score: int
    momentum_score: int
    volume_score: int
    breakout_score: int
    volatility_score: int
    entry_price: float
    atr: float
    adx: float
    rsi: float
    ema20: float
    ema50: float
    volume_ratio: float
    leverage: int = 1
    reason: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class PositionState:
    id: int | None
    symbol: str
    direction: Direction
    entry_price: float
    current_price: float
    size: float
    leverage: int
    initial_atr: float
    sl_price: float
    tp_price: float
    initial_size: float
    remaining_size: float
    score: int
    last_add_price: float = 0.0
    trailing_active: bool = False
    add_count: int = 0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    realized_pnl: float = 0.0
    fee_paid: float = 0.0
    slippage_paid: float = 0.0
    status: str = "OPEN"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def one_r(self) -> float:
        return self.initial_atr * 1.5


@dataclass(slots=True, frozen=True)
class ExitEvent:
    symbol: str
    direction: Direction
    price: float
    size: float
    reason: str
    final: bool
