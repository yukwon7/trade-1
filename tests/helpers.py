from pathlib import Path

from config import Settings
from models import Candle


def settings(root: Path, role: str = "paper") -> Settings:
    return Settings(
        server_role=role, project_dir=root, data_dir=root / "data", config_dir=root / "config",
        database_path=root / "data" / "trades.db", binance_base_url="https://example.test",
        binance_api_key="", binance_secret_key="", telegram_bot_token="token", telegram_chat_id="123",
    )


def candles(count=120, price=100.0):
    return [
        Candle(index * 300_000, price, price + 0.5, price - 0.5, price, 100.0, 10_000.0)
        for index in range(count)
    ]


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, text):
        self.messages.append(text)
        return True

    async def entry(self, position, reason=""):
        self.messages.append(("entry", position.symbol))

    async def closed(self, position, price, pnl, reason):
        self.messages.append(("closed", reason))

    async def circuit_breaker(self, reason, resume_at):
        self.messages.append(("blocked", reason))
