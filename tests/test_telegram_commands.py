import unittest
from types import SimpleNamespace

from notify.telegram_commands import TelegramCommandHandler


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, text):
        self.messages.append(text)
        return True


class FakeTrader:
    def __init__(self):
        self.positions = {}
        self.balance = 1000.0
        self.entry_paused = False
        self.settings = SimpleNamespace(
            max_open_positions=5,
            risk_per_trade=0.01,
            min_score=65,
            max_leverage=5,
            pyramiding_enabled=True,
            trade_frequency_multiplier=1.0,
        )

    async def set_entry_paused(self, value):
        self.entry_paused = value


class FakeStore:
    async def account_pnl(self):
        return 12.5

    async def recent_trades(self, limit):
        return []

    async def performance_rows(self, limit):
        return []

    async def trades_since(self, since):
        return []


class TelegramCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.notifier = FakeNotifier()
        self.trader = FakeTrader()
        self.runtime = SimpleNamespace(current=SimpleNamespace(symbols=("BTCUSDT", "ETHUSDT")))
        self.handler = TelegramCommandHandler(
            None, "token", "123", self.notifier, self.trader, FakeStore(), self.runtime
        )

    async def test_pause_and_resume_change_live_trader(self):
        reply = await self.handler.dispatch("pause")
        self.assertTrue(self.trader.entry_paused)
        self.assertIn("신규 진입 중지", reply)
        await self.handler.dispatch("start")
        self.assertFalse(self.trader.entry_paused)

    async def test_only_configured_chat_can_issue_commands(self):
        await self.handler.handle_update({"message": {"chat": {"id": 999}, "text": "/status"}})
        self.assertEqual(self.notifier.messages, [])
        await self.handler.handle_update({"message": {"chat": {"id": 123}, "text": "/status"}})
        self.assertEqual(len(self.notifier.messages), 1)
        self.assertIn("trade-1 상태", self.notifier.messages[0])

    async def test_legacy_daily_and_stake_commands_respond(self):
        daily = await self.handler.dispatch("daily")
        stake = await self.handler.dispatch("stake", "100")
        self.assertIn("완료된 거래가 없습니다", daily)
        self.assertIn("리스크 기반 주문금액", stake)


if __name__ == "__main__":
    unittest.main()
