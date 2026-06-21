from __future__ import annotations

import asyncio
import hashlib
import logging
import signal as os_signal
import sys
import time
from dataclasses import replace

import aiohttp

from config import RuntimeConfig, Settings
from exchange import BinanceFuturesClient
from models import Candle
from notify import TelegramNotifier
from risk import leverage_for_score
from storage import SQLiteManager, TradeStore
from strategy import SignalEngine
from trader import PaperTrader

logger = logging.getLogger("trade1.paper")


class CandleCache:
    def __init__(self, client: BinanceFuturesClient, maximum: int = 500):
        self.client = client
        self.maximum = maximum
        self.data: dict[tuple[str, str], list[Candle]] = {}

    async def refresh(self, symbol: str, timeframe: str) -> list[Candle]:
        key = (symbol, timeframe)
        incoming = await self.client.get_klines(symbol, timeframe, self.maximum if key not in self.data else 3)
        merged = {item.open_time: item for item in self.data.get(key, [])}
        merged.update({item.open_time: item for item in incoming})
        self.data[key] = sorted(merged.values(), key=lambda item: item.open_time)[-self.maximum :]
        return self.data[key]


class PaperApplication:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.runtime = RuntimeConfig(settings)
        self.stop_event = asyncio.Event()
        self.last_processed: dict[str, int] = {}

    async def run(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.config_dir.mkdir(parents=True, exist_ok=True)
        manager = SQLiteManager(self.settings.database_path)
        await manager.initialize()
        store = TradeStore(manager)
        connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=connector) as session:
            client = BinanceFuturesClient(session, self.settings.binance_base_url, self.settings.binance_api_key)
            notifier = TelegramNotifier(session, self.settings.telegram_bot_token, self.settings.telegram_chat_id)
            trader = PaperTrader(self.settings, store, notifier)
            await trader.initialize()
            cache = CandleCache(client, self.settings.candle_limit)
            engine = SignalEngine()
            await notifier.startup("paper", len(self.settings.symbols))
            tasks = [
                asyncio.create_task(self._signal_loop(client, cache, engine, trader, store, notifier), name="signal-loop"),
                asyncio.create_task(self._position_loop(client, trader, notifier), name="position-loop"),
            ]
            await self.stop_event.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await manager.close()

    async def _signal_loop(self, client, cache, engine, trader, store, notifier) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            current = self.runtime.reload()
            trader.update_settings(current)
            symbols = [item for item in current.symbols if item not in current.symbol_blacklist][: current.symbol_hard_cap]
            results = await asyncio.gather(
                *(self._analyze_symbol(symbol, cache, engine, trader, store, current) for symbol in symbols),
                return_exceptions=True,
            )
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    logger.error("symbol cycle failed %s: %s", symbol, result)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(5.0, self._seconds_to_next_five_minute() - elapsed))

    async def _analyze_symbol(self, symbol, cache, engine, trader, store, settings) -> None:
        candles_1h, candles_15m, candles_5m = await asyncio.gather(
            cache.refresh(symbol, "1h"), cache.refresh(symbol, "15m"), cache.refresh(symbol, "5m")
        )
        if min(len(candles_1h), len(candles_15m), len(candles_5m)) < 60:
            return
        latest = candles_5m[-1]
        if self.last_processed.get(symbol) == latest.open_time:
            return
        self.last_processed[symbol] = latest.open_time
        signal, snapshots = engine.analyze(symbol, candles_1h, candles_15m, candles_5m, settings.min_score)
        if signal and settings.trade_frequency_multiplier < 1.0:
            digest = hashlib.sha256(f"{symbol}:{latest.open_time}".encode()).digest()
            sample = int.from_bytes(digest[:8], "big") / float(2**64)
            if sample >= settings.trade_frequency_multiplier:
                signal = None
        await store.insert_snapshots(snapshots)
        one_hour, fifteen, _ = snapshots
        existing = trader.positions.get(symbol)
        trend_valid = bool(existing) and (
            (existing.direction == "LONG" and one_hour.ema20 > one_hour.ema50 and fifteen.ema20 > fifteen.ema50)
            or (existing.direction == "SHORT" and one_hour.ema20 < one_hour.ema50 and fifteen.ema20 < fifteen.ema50)
        )
        await trader.process_candle(symbol, latest, trend_valid)
        if signal and symbol not in trader.positions:
            leverage = leverage_for_score(signal.score, settings.max_leverage)
            signal = replace(signal, leverage=leverage)
            await store.insert_signal(signal)
            await trader.open(signal)

    async def _position_loop(self, client, trader, notifier) -> None:
        while not self.stop_event.is_set():
            symbols = list(trader.positions)
            if symbols:
                prices = await asyncio.gather(*(client.get_mark_price(symbol) for symbol in symbols), return_exceptions=True)
                for symbol, price in zip(symbols, prices):
                    if isinstance(price, Exception):
                        logger.warning("mark price failed %s: %s", symbol, price)
                        continue
                    synthetic = Candle(int(time.time() * 1000), price, price, price, price, 0.0)
                    await trader.process_candle(symbol, synthetic, trend_valid=False)
            await asyncio.sleep(trader.settings.cycle_seconds)

    @staticmethod
    def _seconds_to_next_five_minute() -> float:
        now = time.time()
        return 300 - (now % 300) + 3


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def async_main() -> None:
    settings = Settings.from_env()
    if settings.server_role != "paper":
        raise RuntimeError("main.py may only run with SERVER_ROLE=paper")
    application = PaperApplication(settings)
    loop = asyncio.get_running_loop()
    for name in (os_signal.SIGINT, os_signal.SIGTERM):
        loop.add_signal_handler(name, application.stop_event.set)
    await application.run()


if __name__ == "__main__":
    setup_logging()
    asyncio.run(async_main())
