import tempfile
import unittest
from pathlib import Path

from notify.telegram_commands import TelegramCommandHandler
from storage import SQLiteManager, TradeStore
from tournament import TournamentController
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
        self.controller = TournamentController(self.settings.config_dir)
        self.handler = TelegramCommandHandler(None, "token", "123", self.notifier, self.trader, self.store, self.controller)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def test_strategy_switch_and_auto(self):
        reply = await self.handler.dispatch("strategy", "S03")
        self.assertIn("S03", reply)
        self.assertEqual(self.controller.active_strategy_id(), "S03")
        await self.handler.dispatch("strategy", "auto")
        self.assertEqual(self.controller.active_strategy_id(), "S01")

    async def test_unauthorized_chat_is_ignored(self):
        await self.handler.handle_update({"message": {"chat": {"id": 999}, "text": "/status"}})
        self.assertEqual(self.notifier.messages, [])

    async def test_tournament_report_command(self):
        reply = await self.handler.dispatch("tournament")
        self.assertIn("TOURNAMENT_REPORT", reply)
        self.assertIn("S01", reply)


if __name__ == "__main__":
    unittest.main()
