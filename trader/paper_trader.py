from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from config import Settings
from models import Candle, StrategySignal, TournamentPosition

logger = logging.getLogger(__name__)


class PaperTrader:
    def __init__(self, settings: Settings, store, notifier):
        self.settings = settings
        self.store = store
        self.notifier = notifier
        self.positions: dict[str, TournamentPosition] = {}
        self.balance = settings.initial_balance
        self.entry_paused = False
        self.max_open_positions = settings.max_open_positions
        self.risk_per_trade = settings.risk_per_trade
        self.max_leverage = settings.max_leverage
        self.daily_loss_limit = 0.05
        self._state_path = settings.config_dir / "paper_state.json"
        self._lock = asyncio.Lock()
        self._notified_blocks: set[tuple[str, str]] = set()

    async def initialize(self) -> None:
        self._load_operator_state()
        self.positions = await self.store.open_positions()
        self.balance = self.settings.initial_balance + await self.store.account_pnl()
        logger.info(
            "router account restored: balance=%.2f positions=%d entry_paused=%s",
            self.balance,
            len(self.positions),
            self.entry_paused,
        )

    def update_runtime_limits(self, risk_config) -> None:
        self.max_open_positions = int(getattr(risk_config, "max_open_positions", self.settings.max_open_positions))
        self.risk_per_trade = float(getattr(risk_config, "risk_per_trade", self.settings.risk_per_trade))
        self.max_leverage = int(getattr(risk_config, "max_leverage", self.settings.max_leverage))
        self.daily_loss_limit = float(getattr(risk_config, "daily_loss_limit", self.daily_loss_limit))

    async def set_entry_paused(self, paused: bool) -> None:
        async with self._lock:
            self.entry_paused = bool(paused)
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"entry_paused": self.entry_paused}), encoding="utf-8")
            temporary.replace(self._state_path)
            logger.info("operator entry pause changed: %s", self.entry_paused)

    async def open(self, signal: StrategySignal) -> TournamentPosition | None:
        async with self._lock:
            if self.entry_paused or signal.symbol in self.positions or len(self.positions) >= self.max_open_positions:
                return None
            allowed, reason, resume_at = await self._allow_entry(signal.symbol, signal.strategy_id)
            if not allowed:
                key = (f"{signal.strategy_id}:{signal.symbol}", reason)
                if key not in self._notified_blocks:
                    self._notified_blocks.add(key)
                    await self.notifier.circuit_breaker(f"{signal.strategy_id} {signal.symbol}: {reason}", resume_at)
                return None
            leverage = max(1, min(self.max_leverage, signal.leverage))
            stop_price = signal.entry_price * (
                1.0 - signal.stop_loss_pct if signal.direction == "LONG" else 1.0 + signal.stop_loss_pct
            )
            take_profit = None
            if signal.take_profit_pct:
                take_profit = signal.entry_price * (
                    1.0 + signal.take_profit_pct if signal.direction == "LONG" else 1.0 - signal.take_profit_pct
                )
            stop_distance = abs(signal.entry_price - stop_price)
            used_margin = sum(item.margin for item in self.positions.values())
            available_margin = max(0.0, self.balance - used_margin)
            per_position_margin = min(available_margin, self.balance / self.max_open_positions)
            loss_per_unit = (
                stop_distance
                + signal.entry_price * (self.settings.fee_rate + self.settings.slippage)
                + stop_price * self.settings.fee_rate
            )
            risk_quantity = self.balance * self.risk_per_trade / loss_per_unit if loss_per_unit else 0.0
            margin_quantity = per_position_margin * leverage / signal.entry_price if signal.entry_price > 0 else 0.0
            quantity = max(0.0, min(risk_quantity, margin_quantity))
            if quantity <= 0:
                return None
            position = TournamentPosition(
                id=None,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                strategy_name=signal.strategy_name,
                direction=signal.direction,
                entry_price=signal.entry_price,
                current_price=signal.entry_price,
                size=quantity,
                leverage=leverage,
                stop_price=stop_price,
                take_profit_price=take_profit,
                balance_before=self.balance,
                metadata=signal.metadata,
                fee_paid=signal.entry_price * quantity * self.settings.fee_rate,
                slippage_paid=signal.entry_price * quantity * self.settings.slippage,
            )
            await self.store.insert_signal(signal)
            await self.store.save_position(position)
            self.positions[position.symbol] = position
            self._notified_blocks = {item for item in self._notified_blocks if not item[0].endswith(f":{signal.symbol}")}
            await self.notifier.entry(position, signal.reason)
            return position

    async def process_tick(self, symbol: str, price: float) -> None:
        async with self._lock:
            position = self.positions.get(symbol)
            if position is None:
                return
            position.current_price = price
            reason = self._fixed_exit(position, price, price)
            if reason:
                await self._close(position, self._exit_price(position, reason, price), reason)
            else:
                await self.store.save_position(position)

    async def process_strategy_candle(self, symbol: str, strategy, candle: Candle, exit_reason: str | None) -> None:
        async with self._lock:
            position = self.positions.get(symbol)
            if position is None:
                return
            position.current_price = candle.close
            reason = self._fixed_exit(position, candle.low, candle.high) or exit_reason
            if reason:
                await self._close(position, self._exit_price(position, reason, candle.close), reason)
            else:
                await self.store.save_position(position)

    async def close_all(self, reason: str = "OPERATOR_CLOSE_ALL") -> int:
        async with self._lock:
            positions = list(self.positions.values())
            for position in positions:
                await self._close(position, position.current_price, reason)
            return len(positions)

    def _fixed_exit(self, position: TournamentPosition, low: float, high: float) -> str | None:
        if position.direction == "LONG":
            if low <= position.stop_price:
                return "STOP_LOSS"
            if position.take_profit_price is not None and high >= position.take_profit_price:
                return "TAKE_PROFIT"
        else:
            if high >= position.stop_price:
                return "STOP_LOSS"
            if position.take_profit_price is not None and low <= position.take_profit_price:
                return "TAKE_PROFIT"
        return None

    @staticmethod
    def _exit_price(position: TournamentPosition, reason: str, fallback: float) -> float:
        if reason == "STOP_LOSS":
            return position.stop_price
        if reason == "TAKE_PROFIT" and position.take_profit_price is not None:
            return position.take_profit_price
        return fallback

    async def _close(self, position: TournamentPosition, price: float, reason: str) -> None:
        gross = (
            (price - position.entry_price) * position.size
            if position.direction == "LONG"
            else (position.entry_price - price) * position.size
        )
        exit_fee = price * position.size * self.settings.fee_rate
        position.fee_paid += exit_fee
        pnl = gross - position.fee_paid - position.slippage_paid
        position.current_price = price
        position.status = "CLOSED"
        self.balance += pnl
        await self.store.insert_trade(position, price, pnl, reason)
        await self.store.delete_position(position.symbol)
        self.positions.pop(position.symbol, None)
        await self.notifier.closed(position, price, pnl, reason)

    async def _allow_entry(self, symbol: str, strategy_id: str) -> tuple[bool, str, str]:
        state = await self.store.risk_state(symbol, strategy_id)
        now = datetime.now(timezone.utc)
        if state["daily_pnl"] <= -(self.settings.initial_balance * self.daily_loss_limit):
            resume = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return False, "DAILY_LOSS_LIMIT_5_PERCENT", resume.isoformat()
        if state["consecutive_losses"] >= 3 and state["last_loss_at"]:
            last_loss = datetime.fromisoformat(state["last_loss_at"])
            resume = last_loss + timedelta(hours=1)
            if now < resume:
                return False, "THREE_CONSECUTIVE_LOSSES", resume.isoformat()
        return True, "OK", ""

    def _load_operator_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.entry_paused = bool(data.get("entry_paused", False))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("invalid operator state %s: %s", self._state_path, exc)
