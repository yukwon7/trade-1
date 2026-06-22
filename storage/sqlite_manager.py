from __future__ import annotations

from pathlib import Path

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS tournament_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    size REAL NOT NULL,
    leverage INTEGER NOT NULL,
    fee REAL NOT NULL,
    slippage REAL NOT NULL,
    pnl REAL NOT NULL,
    return_pct REAL NOT NULL,
    balance_before REAL NOT NULL,
    holding_time INTEGER NOT NULL,
    exit_reason TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'PAPER',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tournament_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL NOT NULL,
    size REAL NOT NULL,
    leverage INTEGER NOT NULL,
    stop_price REAL NOT NULL,
    take_profit_price REAL,
    balance_before REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    fee_paid REAL NOT NULL DEFAULT 0,
    slippage_paid REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    leverage INTEGER NOT NULL,
    stop_loss_pct REAL NOT NULL,
    take_profit_pct REAL,
    reason TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tournament_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluated_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    rankings TEXT NOT NULL,
    best_strategy TEXT,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tournament_trades_strategy ON tournament_trades(strategy_id, exit_time);
CREATE INDEX IF NOT EXISTS idx_tournament_trades_symbol ON tournament_trades(strategy_id, symbol, exit_time);
CREATE INDEX IF NOT EXISTS idx_tournament_trades_exit ON tournament_trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_created ON strategy_signals(strategy_id, created_at);
"""


class SQLiteManager:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.connection is None:
            self.connection = await aiosqlite.connect(self.path)
            self.connection.row_factory = aiosqlite.Row
            await self.connection.execute("PRAGMA journal_mode=WAL")
            await self.connection.execute("PRAGMA synchronous=NORMAL")
            await self.connection.execute("PRAGMA busy_timeout=5000")
            await self.connection.execute("PRAGMA foreign_keys=ON")
        return self.connection

    async def initialize(self) -> None:
        connection = await self.connect()
        await connection.executescript(SCHEMA)
        await connection.commit()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
