import tempfile
import unittest
from pathlib import Path

from models import PositionState
from storage import SQLiteManager, TradeStore


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = SQLiteManager(Path(self.temp.name) / "trades.db")
        await self.manager.initialize()
        self.store = TradeStore(self.manager)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def test_position_round_trip_and_wal(self):
        position = PositionState(
            id=None, symbol="BTCUSDT", direction="LONG", entry_price=100,
            current_price=100, size=1, leverage=2, initial_atr=1,
            sl_price=98.5, tp_price=103, initial_size=1,
            remaining_size=1, score=80,
        )
        await self.store.save_position(position)
        restored = await self.store.open_positions()
        self.assertIn("BTCUSDT", restored)
        db = await self.manager.connect()
        mode = await (await db.execute("PRAGMA journal_mode")).fetchone()
        self.assertEqual(mode[0].lower(), "wal")

    async def test_trade_updates_risk_state(self):
        position = PositionState(
            id=None, symbol="ETHUSDT", direction="SHORT", entry_price=100,
            current_price=101, size=1, leverage=2, initial_atr=1,
            sl_price=101.5, tp_price=97, initial_size=1,
            remaining_size=1, score=75,
        )
        await self.store.insert_trade(position, 102, -2, 0.1, 0.05, "STOP_LOSS")
        state = await self.store.risk_state("ETHUSDT")
        self.assertEqual(state["consecutive_losses"], 1)
        self.assertIsNotNone(state["symbol_last_stop_at"])


if __name__ == "__main__":
    unittest.main()
