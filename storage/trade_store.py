from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from models import StrategySignal, TournamentPosition, utc_now_iso
from storage.sqlite_manager import SQLiteManager


class TradeStore:
    def __init__(self, manager: SQLiteManager):
        self.manager = manager

    async def open_positions(self) -> dict[str, TournamentPosition]:
        db = await self.manager.connect()
        rows = await (await db.execute("SELECT * FROM tournament_positions WHERE status='OPEN'")).fetchall()
        return {row["symbol"]: self._position(row) for row in rows}

    async def save_position(self, position: TournamentPosition) -> int:
        db = await self.manager.connect()
        position.updated_at = utc_now_iso()
        values = (
            position.symbol, position.strategy_id, position.strategy_name, position.direction,
            position.entry_price, position.current_price, position.size, position.leverage,
            position.stop_price, position.take_profit_price, position.balance_before,
            json.dumps(position.metadata, separators=(",", ":")), position.fee_paid,
            position.slippage_paid, position.status, position.created_at, position.updated_at,
        )
        await db.execute(
            """INSERT INTO tournament_positions (
                symbol,strategy_id,strategy_name,direction,entry_price,current_price,size,leverage,
                stop_price,take_profit_price,balance_before,metadata,fee_paid,slippage_paid,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                strategy_id=excluded.strategy_id,strategy_name=excluded.strategy_name,direction=excluded.direction,
                entry_price=excluded.entry_price,current_price=excluded.current_price,size=excluded.size,
                leverage=excluded.leverage,stop_price=excluded.stop_price,take_profit_price=excluded.take_profit_price,
                balance_before=excluded.balance_before,metadata=excluded.metadata,fee_paid=excluded.fee_paid,
                slippage_paid=excluded.slippage_paid,status=excluded.status,updated_at=excluded.updated_at""",
            values,
        )
        await db.commit()
        row = await (await db.execute("SELECT id FROM tournament_positions WHERE symbol=?", (position.symbol,))).fetchone()
        position.id = int(row["id"])
        return position.id

    async def delete_position(self, symbol: str) -> None:
        db = await self.manager.connect()
        await db.execute("DELETE FROM tournament_positions WHERE symbol=?", (symbol,))
        await db.commit()

    async def insert_signal(self, signal: StrategySignal) -> None:
        db = await self.manager.connect()
        await db.execute(
            """INSERT INTO strategy_signals (
                strategy_id,strategy_name,symbol,direction,entry_price,leverage,
                stop_loss_pct,take_profit_pct,reason,metadata,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal.strategy_id, signal.strategy_name, signal.symbol, signal.direction,
                signal.entry_price, signal.leverage, signal.stop_loss_pct, signal.take_profit_pct,
                signal.reason, json.dumps(signal.metadata, separators=(",", ":")), signal.created_at,
            ),
        )
        await db.commit()

    async def insert_trade(self, position: TournamentPosition, exit_price: float, pnl: float, exit_reason: str) -> int:
        db = await self.manager.connect()
        now = datetime.now(timezone.utc)
        entered = datetime.fromisoformat(position.created_at)
        holding = max(0, int((now - entered).total_seconds()))
        return_pct = pnl / position.balance_before if position.balance_before > 0 else 0.0
        cursor = await db.execute(
            """INSERT INTO tournament_trades (
                strategy_id,strategy_name,symbol,direction,entry_price,exit_price,entry_time,exit_time,
                size,leverage,fee,slippage,pnl,return_pct,balance_before,holding_time,exit_reason,source,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PAPER',?)""",
            (
                position.strategy_id, position.strategy_name, position.symbol, position.direction,
                position.entry_price, exit_price, position.created_at, now.isoformat(), position.size,
                position.leverage, position.fee_paid, position.slippage_paid, pnl, return_pct,
                position.balance_before, holding, exit_reason, now.isoformat(),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)

    async def account_pnl(self) -> float:
        db = await self.manager.connect()
        row = await (await db.execute("SELECT COALESCE(SUM(pnl),0) AS value FROM tournament_trades WHERE source='PAPER'")).fetchone()
        return float(row["value"])

    async def risk_state(self, symbol: str, strategy_id: str) -> dict[str, Any]:
        db = await self.manager.connect()
        today = datetime.now(timezone.utc).date().isoformat()
        daily = await (
            await db.execute(
                "SELECT COALESCE(SUM(pnl),0) value FROM tournament_trades WHERE source='PAPER' AND substr(exit_time,1,10)=?",
                (today,),
            )
        ).fetchone()
        rows = await (
            await db.execute(
                """SELECT pnl,exit_time FROM tournament_trades
                   WHERE source='PAPER' AND symbol=? AND strategy_id=? ORDER BY id DESC LIMIT 20""",
                (symbol, strategy_id),
            )
        ).fetchall()
        consecutive = 0
        last_loss_at = None
        for row in rows:
            if float(row["pnl"]) < 0:
                consecutive += 1
                last_loss_at = last_loss_at or row["exit_time"]
            else:
                break
        return {"daily_pnl": float(daily["value"]), "consecutive_losses": consecutive, "last_loss_at": last_loss_at}

    async def performance_rows(self, limit: int = 10000):
        db = await self.manager.connect()
        return await (
            await db.execute(
                "SELECT * FROM tournament_trades WHERE source='PAPER' ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        ).fetchall()

    async def strategy_rows(self, strategy_id: str | None = None):
        db = await self.manager.connect()
        if strategy_id:
            return await (
                await db.execute(
                    "SELECT * FROM tournament_trades WHERE source='PAPER' AND strategy_id=? ORDER BY id",
                    (strategy_id,),
                )
            ).fetchall()
        return await (await db.execute("SELECT * FROM tournament_trades WHERE source='PAPER' ORDER BY id")).fetchall()

    async def recent_trades(self, limit: int = 10):
        db = await self.manager.connect()
        return await (
            await db.execute(
                "SELECT * FROM tournament_trades WHERE source='PAPER' ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            )
        ).fetchall()

    async def trades_since(self, since: str):
        db = await self.manager.connect()
        return await (
            await db.execute(
                "SELECT * FROM tournament_trades WHERE source='PAPER' AND exit_time>=? ORDER BY id DESC",
                (since,),
            )
        ).fetchall()

    @staticmethod
    def _position(row) -> TournamentPosition:
        return TournamentPosition(
            id=row["id"], symbol=row["symbol"], strategy_id=row["strategy_id"],
            strategy_name=row["strategy_name"], direction=row["direction"],
            entry_price=float(row["entry_price"]), current_price=float(row["current_price"]),
            size=float(row["size"]), leverage=int(row["leverage"]), stop_price=float(row["stop_price"]),
            take_profit_price=float(row["take_profit_price"]) if row["take_profit_price"] is not None else None,
            balance_before=float(row["balance_before"]), metadata=json.loads(row["metadata"] or "{}"),
            fee_paid=float(row["fee_paid"]), slippage_paid=float(row["slippage_paid"]),
            status=row["status"], created_at=row["created_at"], updated_at=row["updated_at"],
        )
