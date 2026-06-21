from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, direction TEXT NOT NULL,
    entry_price REAL NOT NULL, exit_price REAL,
    entry_time TEXT NOT NULL, exit_time TEXT,
    size REAL NOT NULL, leverage INTEGER NOT NULL,
    score INTEGER NOT NULL, add_count INTEGER NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0, slippage REAL NOT NULL DEFAULT 0,
    pnl REAL, holding_time INTEGER, exit_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE, direction TEXT NOT NULL,
    entry_price REAL NOT NULL, current_price REAL NOT NULL,
    size REAL NOT NULL, remaining_size REAL NOT NULL,
    initial_size REAL NOT NULL, initial_atr REAL NOT NULL,
    leverage INTEGER NOT NULL, score INTEGER NOT NULL,
    last_add_price REAL NOT NULL,
    sl_price REAL NOT NULL, tp_price REAL NOT NULL,
    trailing_active INTEGER NOT NULL DEFAULT 0,
    add_count INTEGER NOT NULL DEFAULT 0,
    highest_price REAL NOT NULL, lowest_price REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    fee_paid REAL NOT NULL DEFAULT 0,
    slippage_paid REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, direction TEXT NOT NULL, score INTEGER NOT NULL,
    trend_score INTEGER NOT NULL, momentum_score INTEGER NOT NULL,
    volume_score INTEGER NOT NULL, breakout_score INTEGER NOT NULL,
    volatility_score INTEGER NOT NULL,
    rsi REAL NOT NULL, adx REAL NOT NULL, atr REAL NOT NULL,
    ema20 REAL NOT NULL, ema50 REAL NOT NULL, volume_ratio REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS indicator_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
    ema20 REAL NOT NULL, ema50 REAL NOT NULL, rsi REAL NOT NULL,
    adx REAL NOT NULL, atr REAL NOT NULL, volume_ratio REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL UNIQUE,
    total_trades INTEGER NOT NULL, win_trades INTEGER NOT NULL,
    loss_trades INTEGER NOT NULL, win_rate REAL NOT NULL,
    profit_factor REAL NOT NULL, total_pnl REAL NOT NULL,
    max_dd REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS optimizer_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_time TEXT NOT NULL,
    analyzed_trades INTEGER NOT NULL, win_rate REAL NOT NULL,
    profit_factor REAL NOT NULL, mdd REAL NOT NULL,
    adjustments TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol, exit_time);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_tf ON indicator_snapshots(symbol, timeframe, created_at);
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
