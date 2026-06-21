from __future__ import annotations

import asyncio
import json
import logging

from config import Settings
from models import Candle, PositionState, Signal
from risk import CircuitBreaker, PyramidManager, StopManager, calculate_position_size
from storage import TradeStore
from trader.position import new_position

logger = logging.getLogger(__name__)


class PaperTrader:
    def __init__(self, settings: Settings, store: TradeStore, notifier):
        self.settings = settings
        self.store = store
        self.notifier = notifier
        self.circuit = CircuitBreaker(store)
        self.positions: dict[str, PositionState] = {}
        self.balance = settings.initial_balance
        self.entry_paused = False
        self._state_path = settings.config_dir / "paper_state.json"
        self._lock = asyncio.Lock()
        self._notified_blocks: set[tuple[str, str]] = set()

    async def initialize(self) -> None:
        self._load_operator_state()
        self.positions = await self.store.open_positions()
        self.balance = self.settings.initial_balance + await self.store.account_pnl()
        logger.info(
            "paper account restored: balance=%.2f open_positions=%d entry_paused=%s",
            self.balance,
            len(self.positions),
            self.entry_paused,
        )

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings

    async def set_entry_paused(self, paused: bool) -> None:
        async with self._lock:
            self.entry_paused = bool(paused)
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"entry_paused": self.entry_paused}), encoding="utf-8")
            temporary.replace(self._state_path)
            logger.info("operator entry pause changed: %s", self.entry_paused)

    def _load_operator_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.entry_paused = bool(data.get("entry_paused", False))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("invalid operator state %s: %s", self._state_path, exc)

    async def open(self, signal: Signal) -> PositionState | None:
        async with self._lock:
            if self.entry_paused or signal.symbol in self.positions or len(self.positions) >= self.settings.max_open_positions:
                return None
            allowed, reason, resume_at = await self.circuit.allow_entry(signal.symbol, self.balance)
            if not allowed:
                logger.info("entry blocked %s: %s", signal.symbol, reason)
                key = (signal.symbol, reason)
                if key not in self._notified_blocks:
                    self._notified_blocks.add(key)
                    await self.notifier.circuit_breaker(f"{signal.symbol}: {reason}", resume_at)
                return None
            self._notified_blocks = {item for item in self._notified_blocks if item[0] != signal.symbol}
            stop, _ = StopManager.initial_levels(signal.direction, signal.entry_price, signal.atr)
            used_margin = sum(p.remaining_size * p.current_price / p.leverage for p in self.positions.values())
            quantity = calculate_position_size(
                self.balance,
                self.settings.risk_per_trade,
                signal.entry_price,
                stop,
                signal.leverage,
                max(0.0, self.balance - used_margin),
            )
            if quantity <= 0:
                return None
            position = new_position(signal, quantity)
            entry_fee = position.entry_price * position.remaining_size * self.settings.fee_rate
            entry_slippage = position.entry_price * position.remaining_size * self.settings.slippage
            position.fee_paid = entry_fee
            position.slippage_paid = entry_slippage
            await self.store.save_position(position)
            self.positions[position.symbol] = position
            await self.notifier.entry(position)
            return position

    async def process_candle(self, symbol: str, candle: Candle, trend_valid: bool = True) -> None:
        async with self._lock:
            position = self.positions.get(symbol)
            if position is None:
                return
            event = StopManager.update(position, candle.high, candle.low, candle.close)
            if event:
                await self._execute_exit(position, event.price, event.size, event.reason, event.final)
                if event.final:
                    return
            if self.settings.pyramiding_enabled and symbol in self.positions:
                add_size = PyramidManager.next_add_size(position, candle.close, trend_valid)
                if add_size > 0:
                    await self._add(position, candle.close, add_size)
            if symbol in self.positions:
                await self.store.save_position(position)

    async def _add(self, position: PositionState, price: float, quantity: float) -> None:
        used_margin = sum(p.remaining_size * p.current_price / p.leverage for p in self.positions.values())
        available_margin = max(0.0, self.balance - used_margin)
        quantity = min(quantity, available_margin * position.leverage / price)
        if quantity <= 0:
            return
        old_size = position.remaining_size
        new_size = old_size + quantity
        position.entry_price = (position.entry_price * old_size + price * quantity) / new_size
        position.size += quantity
        position.remaining_size = new_size
        position.add_count += 1
        position.last_add_price = price
        position.fee_paid += price * quantity * self.settings.fee_rate
        position.slippage_paid += price * quantity * self.settings.slippage
        await self.store.save_position(position)
        await self.notifier.pyramid(position, price, quantity)

    async def _execute_exit(self, position: PositionState, price: float, quantity: float, reason: str, final: bool) -> None:
        quantity = min(quantity, position.remaining_size)
        gross = (price - position.entry_price) * quantity if position.direction == "LONG" else (position.entry_price - price) * quantity
        exit_fee = price * quantity * self.settings.fee_rate
        allocated_entry_fee = position.entry_price * quantity * self.settings.fee_rate
        allocated_slippage = position.entry_price * quantity * self.settings.slippage
        pnl = gross - exit_fee - allocated_entry_fee - allocated_slippage
        position.realized_pnl += pnl
        position.fee_paid += exit_fee
        position.remaining_size -= quantity
        self.balance += pnl
        if final or position.remaining_size <= 1e-12:
            position.status = "CLOSED"
            total_pnl = position.realized_pnl
            await self.store.insert_trade(position, price, total_pnl, position.fee_paid, position.slippage_paid, reason)
            await self.store.delete_position(position.symbol)
            self.positions.pop(position.symbol, None)
            await self.notifier.closed(position, price, total_pnl, reason)
        else:
            await self.store.save_position(position)
            await self.notifier.partial_close(position, price, quantity, pnl)
