import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from analytics.stress_tester import run_stress_test
from models import StrategySignal, TournamentPosition
from storage import SQLiteManager, TradeStore
from router import RouterController
from trader import PaperTrader
from tests.helpers import FakeNotifier, settings


class ControllerTests(unittest.TestCase):
    def test_manual_strategy_and_auto_router(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = RouterController(Path(directory))
            controller.set_manual_strategy("S20")
            self.assertEqual(controller.active_strategy_id(), "S20")
            controller.set_manual_strategy(None)
            self.assertEqual(controller.active_strategy_id(), "S99")
            self.assertEqual(controller.status()["source"], "ROUTER")


class RouterAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = settings(self.root)
        self.manager = SQLiteManager(self.settings.database_path)
        await self.manager.initialize()
        self.store = TradeStore(self.manager)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def test_position_round_trip_and_stop_close(self):
        notifier = FakeNotifier()
        trader = PaperTrader(self.settings, self.store, notifier)
        await trader.initialize()
        signal = StrategySignal("S20", "EMA9_21_PULLBACK", "BTCUSDT", "LONG", 100, 3, 0.012, None, "test")
        position = await trader.open(signal)
        self.assertIsNotNone(position)
        self.assertLessEqual(position.margin, trader.balance / self.settings.max_open_positions)
        await trader.process_tick("BTCUSDT", position.stop_price)
        self.assertNotIn("BTCUSDT", trader.positions)
        rows = await self.store.strategy_rows("S20")
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["pnl"], 0)
        self.assertGreaterEqual(rows[0]["pnl"], -self.settings.initial_balance * 0.020001)

    async def test_stress_test_ignores_legacy_strategy_rows(self):
        for strategy_id in ("LEGACY", "S20"):
            position = TournamentPosition(
                None, "BTCUSDT", strategy_id, "TEST", "LONG", 100, 100, 1, 3,
                99, None, 1000, created_at=datetime.now().astimezone().isoformat(),
            )
            await self.store.insert_trade(position, 101, 1.0, "TEST")
        report = run_stress_test(self.settings, persist=False)
        self.assertEqual(report["trade_count"], 2)
        self.assertEqual(report["router_trade_count"], 1)
        self.assertEqual(report["candidate_trade_count"], 1)


if __name__ == "__main__":
    unittest.main()
