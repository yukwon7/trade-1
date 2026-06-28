import tempfile
import unittest
from pathlib import Path

from notify.telegram_commands import TelegramCommandHandler
from storage import SQLiteManager, TradeStore
from router import RouterController
from trader import PaperTrader
from tests.helpers import FakeNotifier, settings


class TelegramTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = settings(root)
        self.manager = SQLiteManager(self.settings.database_path)
        await self.manager.initialize()
        self.store = TradeStore(self.manager)
        self.notifier = FakeNotifier()
        self.trader = PaperTrader(self.settings, self.store, self.notifier)
        await self.trader.initialize()
        self.controller = RouterController(self.settings.config_dir)
        self.handler = TelegramCommandHandler(None, "token", "123", self.notifier, self.trader, self.store, self.controller)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def test_strategy_switch_and_auto(self):
        reply = await self.handler.dispatch("strategy", "S20")
        self.assertIn("S20", reply)
        self.assertEqual(self.controller.active_strategy_id(), "S20")
        await self.handler.dispatch("strategy", "auto")
        self.assertEqual(self.controller.active_strategy_id(), "S99")

    async def test_unauthorized_chat_is_ignored(self):
        await self.handler.handle_update({"message": {"chat": {"id": 999}, "text": "/status"}})
        self.assertEqual(self.notifier.messages, [])

    async def test_router_command_without_snapshot(self):
        reply = await self.handler.dispatch("router")
        self.assertIn("차트 라우터", reply)

    async def test_stress_report_command(self):
        reply = await self.handler.dispatch("stress")
        self.assertIn("STRESS_TEST_REPORT", reply)

    async def test_short_commands(self):
        self.assertIn("trade-1", await self.handler.dispatch("s"))
        self.assertIn("차트 라우터", await self.handler.dispatch("r"))
        self.assertIn("차트 상태", await self.handler.dispatch("g", "BTCUSDT"))
        self.assertIn("전략 카탈로그", await self.handler.dispatch("cat"))
        self.assertIn("STRESS_TEST_REPORT", await self.handler.dispatch("x"))
        self.assertIn("S99", await self.handler.dispatch("set", "S99"))
        self.assertIn("S99", await self.handler.dispatch("s99"))


if __name__ == "__main__":
    unittest.main()
