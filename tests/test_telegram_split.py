from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from execution.config_reloader import ConfigReloader
from notify.telegram_execution_bot import TelegramExecutionCommandHandler


class TelegramSplitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = SimpleNamespace(
            config_dir=Path(self.tmp.name),
            max_open_positions=3,
        )
        trader = SimpleNamespace(
            settings=settings,
            balance=1000.0,
            positions={},
            entry_paused=False,
            set_entry_paused=self._set_paused,
            close_all=self._close_all,
        )
        self.paused = False
        self.handler = TelegramExecutionCommandHandler(
            None, "token", "123", SimpleNamespace(send=None), trader, None, ConfigReloader(settings.config_dir)
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def _set_paused(self, value):
        self.paused = value
        self.handler.trader.entry_paused = value

    async def _close_all(self, reason):
        return 0

    async def test_execution_bot_rejects_heavy_stress_command(self):
        reply = await self.handler.dispatch("stress")
        self.assertIn("지원하지 않는 실행 명령", reply)

    async def test_close_all_requires_confirmation(self):
        reply = await self.handler.dispatch("close_all")
        self.assertIn("CONFIRM", reply)


if __name__ == "__main__":
    unittest.main()
