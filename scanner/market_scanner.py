from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import aiohttp

from config import Settings
from exchange import BinanceFuturesClient
from notify import TelegramNotifier


class MarketScanner:
    def __init__(self, settings: Settings, client: BinanceFuturesClient, notifier: TelegramNotifier | None = None):
        self.settings = settings
        self.client = client
        self.notifier = notifier
        self.path = settings.config_dir / "selected_symbols.json"

    async def run(self) -> list[str]:
        info, tickers = await asyncio.gather(self.client.get_exchange_info(), self.client.get_all_tickers())
        valid = {
            item["symbol"]
            for item in info.get("symbols", [])
            if item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and item.get("status") == "TRADING"
        }
        ranked = sorted(
            (item for item in tickers if item.get("symbol") in valid),
            key=lambda item: float(item.get("quoteVolume", 0)),
            reverse=True,
        )
        symbols = [item["symbol"] for item in ranked[: self.settings.symbol_hard_cap]]
        previous = self._read_symbols()
        payload = {
            "symbols": symbols,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "binance_24h_volume_top15",
        }
        self._atomic_write(payload)
        if self.notifier and previous != symbols:
            await self.notifier.symbols_changed(previous, symbols)
        return symbols

    def _read_symbols(self) -> list[str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("symbols", []) if self.path.exists() else []
        except (OSError, json.JSONDecodeError):
            return []

    def _atomic_write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


async def main() -> None:
    settings = Settings.from_env()
    if settings.server_role != "analysis":
        raise RuntimeError("scanner may only run with SERVER_ROLE=analysis")
    async with aiohttp.ClientSession() as session:
        client = BinanceFuturesClient(session, settings.binance_base_url, settings.binance_api_key)
        notifier = TelegramNotifier(session, settings.telegram_bot_token, settings.telegram_chat_id)
        symbols = await MarketScanner(settings, client, notifier).run()
        print("\n".join(symbols))


if __name__ == "__main__":
    asyncio.run(main())
