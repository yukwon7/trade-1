from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from models import IndicatorSnapshot, PositionState, Signal, utc_now_iso
from storage.sqlite_manager import SQLiteManager


class TradeStore:
    def __init__(self, manager: SQLiteManager):
        self.manager = manager

    async def open_positions(self) -> dict[str, PositionState]:
        db = await self.manager.connect()
        rows = await (await db.execute("SELECT * FROM positions WHERE status='OPEN'")).fetchall()
        return {row["symbol"]: self._position(row) for row in rows}

    async def save_position(self, position: PositionState) -> int:
        db = await self.manager.connect()
        values = (
            position.symbol, position.direction, position.entry_price, position.current_price,
            position.size, position.remaining_size, position.initial_size, position.initial_atr,
            position.leverage, position.score, position.last_add_price, position.sl_price, position.tp_price,
            int(position.trailing_active), position.add_count, position.highest_price,
            position.lowest_price, position.realized_pnl, position.fee_paid,
            position.slippage_paid, position.status, position.created_at, utc_now_iso(),
        )
        await db.execute(
            """INSERT INTO positions (
                symbol,direction,entry_price,current_price,size,remaining_size,initial_size,initial_atr,
                leverage,score,last_add_price,sl_price,tp_price,trailing_active,add_count,highest_price,lowest_price,
                realized_pnl,fee_paid,slippage_paid,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                direction=excluded.direction,entry_price=excluded.entry_price,current_price=excluded.current_price,
                size=excluded.size,remaining_size=excluded.remaining_size,initial_size=excluded.initial_size,
                initial_atr=excluded.initial_atr,leverage=excluded.leverage,score=excluded.score,last_add_price=excluded.last_add_price,
                sl_price=excluded.sl_price,tp_price=excluded.tp_price,trailing_active=excluded.trailing_active,
                add_count=excluded.add_count,highest_price=excluded.highest_price,lowest_price=excluded.lowest_price,
                realized_pnl=excluded.realized_pnl,fee_paid=excluded.fee_paid,slippage_paid=excluded.slippage_paid,
                status=excluded.status,updated_at=excluded.updated_at""",
            values,
        )
        await db.commit()
        row = await (await db.execute("SELECT id FROM positions WHERE symbol=?", (position.symbol,))).fetchone()
        position.id = int(row["id"])
        return position.id

    async def delete_position(self, symbol: str) -> None:
        db = await self.manager.connect()
        await db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        await db.commit()

    async def insert_trade(
        self, position: PositionState, exit_price: float, pnl: float, fee: float,
        slippage: float, exit_reason: str,
    ) -> int:
        db = await self.manager.connect()
        now = datetime.now(timezone.utc)
        entered = datetime.fromisoformat(position.created_at)
        holding = max(0, int((now - entered).total_seconds()))
        cursor = await db.execute(
            """INSERT INTO trades (
                symbol,direction,entry_price,exit_price,entry_time,exit_time,size,leverage,score,
                add_count,fee,slippage,pnl,holding_time,exit_reason,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                position.symbol, position.direction, position.entry_price, exit_price,
                position.created_at, now.isoformat(), position.size, position.leverage,
                position.score, position.add_count, fee, slippage, pnl, holding, exit_reason, now.isoformat(),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)

    async def insert_signal(self, signal: Signal) -> None:
        db = await self.manager.connect()
        await db.execute(
            """INSERT INTO signals (
                symbol,direction,score,trend_score,momentum_score,volume_score,breakout_score,
                volatility_score,rsi,adx,atr,ema20,ema50,volume_ratio,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal.symbol, signal.direction, signal.score, signal.trend_score,
                signal.momentum_score, signal.volume_score, signal.breakout_score,
                signal.volatility_score, signal.rsi, signal.adx, signal.atr,
                signal.ema20, signal.ema50, signal.volume_ratio, signal.created_at,
            ),
        )
        await db.commit()

    async def insert_snapshots(self, snapshots: tuple[IndicatorSnapshot, ...]) -> None:
        db = await self.manager.connect()
        await db.executemany(
            """INSERT INTO indicator_snapshots
               (symbol,timeframe,ema20,ema50,rsi,adx,atr,volume_ratio,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(x.symbol, x.timeframe, x.ema20, x.ema50, x.rsi, x.adx, x.atr, x.volume_ratio, x.created_at) for x in snapshots],
        )
        await db.commit()

    async def account_pnl(self) -> float:
        db = await self.manager.connect()
        closed = await (await db.execute("SELECT COALESCE(SUM(pnl),0) AS value FROM trades")).fetchone()
        partial = await (await db.execute("SELECT COALESCE(SUM(realized_pnl),0) AS value FROM positions WHERE status='OPEN'")).fetchone()
        return float(closed["value"]) + float(partial["value"])

    async def risk_state(self, symbol: str) -> dict[str, Any]:
        db = await self.manager.connect()
        today = datetime.now(timezone.utc).date().isoformat()
        daily = await (await db.execute("SELECT COALESCE(SUM(pnl),0) value FROM trades WHERE substr(exit_time,1,10)=?", (today,))).fetchone()
        recent = await (await db.execute("SELECT pnl,exit_reason,exit_time FROM trades ORDER BY id DESC LIMIT 50")).fetchall()
        symbol_rows = await (await db.execute("SELECT pnl,exit_reason,exit_time FROM trades WHERE symbol=? ORDER BY id DESC LIMIT 10", (symbol,))).fetchall()
        consecutive = 0
        last_loss_at = None
        for row in recent:
            if float(row["pnl"] or 0) < 0:
                consecutive += 1
                last_loss_at = last_loss_at or row["exit_time"]
            else:
                break
        losses = sum(1 for row in symbol_rows if float(row["pnl"] or 0) < 0)
        last_symbol_loss = next((row["exit_time"] for row in symbol_rows if float(row["pnl"] or 0) < 0), None)
        last_stop = next((row["exit_time"] for row in symbol_rows if row["exit_reason"] == "STOP_LOSS"), None)
        return {
            "daily_pnl": float(daily["value"]), "consecutive_losses": consecutive,
            "last_loss_at": last_loss_at, "symbol_last_10_losses": losses,
            "symbol_last_10_count": len(symbol_rows),
            "symbol_last_loss_at": last_symbol_loss, "symbol_last_stop_at": last_stop,
        }

    async def performance_rows(self, limit: int = 1000):
        db = await self.manager.connect()
        return await (await db.execute("SELECT * FROM trades WHERE exit_time IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))).fetchall()

    async def recent_trades(self, limit: int = 10):
        db = await self.manager.connect()
        return await (
            await db.execute(
                "SELECT * FROM trades WHERE exit_time IS NOT NULL ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            )
        ).fetchall()

    async def trades_since(self, since: str):
        db = await self.manager.connect()
        return await (
            await db.execute(
                "SELECT * FROM trades WHERE exit_time IS NOT NULL AND exit_time>=? ORDER BY id DESC",
                (since,),
            )
        ).fetchall()

    async def log_optimizer(self, metrics: dict[str, Any], adjustments: dict[str, Any]) -> None:
        db = await self.manager.connect()
        now = utc_now_iso()
        await db.execute(
            "INSERT INTO optimizer_logs (run_time,analyzed_trades,win_rate,profit_factor,mdd,adjustments,created_at) VALUES (?,?,?,?,?,?,?)",
            (now, metrics["trades"], metrics["win_rate"], metrics["profit_factor"], metrics["mdd"], json.dumps(adjustments), now),
        )
        await db.commit()

    @staticmethod
    def _position(row) -> PositionState:
        return PositionState(
            id=row["id"], symbol=row["symbol"], direction=row["direction"],
            entry_price=row["entry_price"], current_price=row["current_price"],
            size=row["size"], remaining_size=row["remaining_size"], initial_size=row["initial_size"],
            initial_atr=row["initial_atr"], leverage=row["leverage"], score=row["score"],
            last_add_price=row["last_add_price"],
            sl_price=row["sl_price"], tp_price=row["tp_price"], trailing_active=bool(row["trailing_active"]),
            add_count=row["add_count"], highest_price=row["highest_price"], lowest_price=row["lowest_price"],
            realized_pnl=row["realized_pnl"], fee_paid=row["fee_paid"], slippage_paid=row["slippage_paid"],
            status=row["status"], created_at=row["created_at"], updated_at=row["updated_at"],
        )
