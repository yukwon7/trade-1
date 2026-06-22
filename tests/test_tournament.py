import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from analytics.tournament_evaluator import TournamentEvaluator
from models import StrategySignal, TournamentPosition
from storage import SQLiteManager, TradeStore
from tournament import TournamentController
from trader import PaperTrader
from tests.helpers import FakeNotifier, settings


class ControllerTests(unittest.TestCase):
    def test_manual_strategy_and_auto_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = TournamentController(Path(directory), "MODE_B")
            controller.set_manual_strategy("S07")
            self.assertEqual(controller.active_strategy_id(), "S07")
            controller.set_manual_strategy(None)
            self.assertEqual(controller.active_strategy_id(), "S01")
            controller.set_mode("A")
            self.assertEqual(controller.mode, "MODE_A")

    def test_mode_b_rotates_on_utc_hour_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = TournamentController(Path(directory), "MODE_B")
            controller._control["rotation_started_at"] = "2026-06-22T10:00:00+00:00"
            self.assertEqual(controller.active_strategy_id(datetime(2026, 6, 22, 10, 59, tzinfo=timezone.utc)), "S01")
            self.assertEqual(controller.active_strategy_id(datetime(2026, 6, 22, 11, 0, tzinfo=timezone.utc)), "S02")


class TournamentAsyncTests(unittest.IsolatedAsyncioTestCase):
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
        signal = StrategySignal("S02", "EMA_CROSS_FAST", "BTCUSDT", "LONG", 100, 7, 0.012, None, "test")
        position = await trader.open(signal)
        self.assertIsNotNone(position)
        self.assertLessEqual(position.margin, trader.balance / 4)
        await trader.process_tick("BTCUSDT", position.stop_price)
        self.assertNotIn("BTCUSDT", trader.positions)
        rows = await self.store.strategy_rows("S02")
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["pnl"], 0)
        self.assertGreaterEqual(rows[0]["pnl"], -self.settings.initial_balance * 0.020001)

    async def test_evaluator_locks_eligible_strategy(self):
        for index in range(10):
            pnl = 2.0 if index < 6 else -1.0
            position = TournamentPosition(
                None, "BTCUSDT", "S01", "HA_RSI_VSA", "LONG", 100, 100, 1, 5,
                99, None, 1000, created_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.store.insert_trade(position, 101 if pnl > 0 else 99, pnl, "TEST")
        report = await TournamentEvaluator(self.settings, self.store).evaluate()
        self.assertEqual(report["best_strategy"], "S01")
        self.assertEqual(report["action"], "LOCK")
        self.assertTrue((self.settings.config_dir / "tournament_result.json").exists())


if __name__ == "__main__":
    unittest.main()
