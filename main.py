from __future__ import annotations

import asyncio
import logging
import signal as os_signal
import sys
import time

import aiohttp

from config import Settings
from exchange import BinanceFuturesClient
from notify import TelegramCommandHandler, TelegramNotifier
from storage import SQLiteManager, TradeStore
from strategies import get_strategy
from tournament import TournamentController
from trader import PaperTrader

logger = logging.getLogger("trade1.tournament")


class CandleCache:
    def __init__(self, client: BinanceFuturesClient, maximum: int = 300):
        self.client = client
        self.maximum = maximum
        self.data = {}

    async def refresh(self, symbol: str, timeframe: str):
        key = (symbol, timeframe)
        incoming = await self.client.get_klines(symbol, timeframe, self.maximum if key not in self.data else 3)
        merged = {item.open_time: item for item in self.data.get(key, [])}
        merged.update({item.open_time: item for item in incoming})
        self.data[key] = sorted(merged.values(), key=lambda item: item.open_time)[-self.maximum :]
        return self.data[key]


class PaperApplication:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stop_event = asyncio.Event()
        self.last_processed: dict[str, int] = {}
        self.last_active_strategy = ""

    async def run(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.config_dir.mkdir(parents=True, exist_ok=True)
        manager = SQLiteManager(self.settings.database_path)
        await manager.initialize()
        store = TradeStore(manager)
        controller = TournamentController(self.settings.config_dir, self.settings.tournament_mode)
        connector = aiohttp.TCPConnector(limit=24, ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=connector) as session:
            client = BinanceFuturesClient(session, self.settings.binance_base_url, self.settings.binance_api_key)
            notifier = TelegramNotifier(session, self.settings.telegram_bot_token, self.settings.telegram_chat_id)
            trader = PaperTrader(self.settings, store, notifier)
            await trader.initialize()
            commands = TelegramCommandHandler(
                session, self.settings.telegram_bot_token, self.settings.telegram_chat_id,
                notifier, trader, store, controller,
            )
            cache = CandleCache(client, self.settings.candle_limit)
            status = controller.status()
            await notifier.startup("paper", len(self.settings.symbols), f"{status['active_strategy']} ({status['source']})")
            tasks = [
                asyncio.create_task(self._signal_loop(client, cache, controller, trader, notifier), name="strategy-loop"),
                asyncio.create_task(self._position_loop(client, trader), name="position-loop"),
                asyncio.create_task(commands.run(self.stop_event), name="telegram-command-loop"),
            ]
            await self.stop_event.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await manager.close()

    async def _signal_loop(self, client, cache, controller, trader, notifier) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            active = controller.active_strategy()
            status = controller.status()
            if active.strategy_id != self.last_active_strategy:
                await notifier.strategy_changed(self.last_active_strategy, active.strategy_id, status["source"])
                logger.info("active strategy changed: %s %s", active.strategy_id, active.name)
                self.last_active_strategy = active.strategy_id
            results = await asyncio.gather(
                *(self._analyze_symbol(symbol, active, client, cache, trader) for symbol in self.settings.symbols),
                return_exceptions=True,
            )
            for symbol, result in zip(self.settings.symbols, results):
                if isinstance(result, Exception):
                    logger.error("strategy cycle failed %s: %s", symbol, result)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(5.0, self._seconds_to_next_five_minute() - elapsed))

    async def _analyze_symbol(self, symbol, active, client, cache, trader) -> None:
        candles_5m, candles_15m = await asyncio.gather(cache.refresh(symbol, "5m"), cache.refresh(symbol, "15m"))
        if min(len(candles_5m), len(candles_15m)) < 100:
            return
        latest = candles_5m[-1]
        if self.last_processed.get(symbol) == latest.open_time:
            return
        self.last_processed[symbol] = latest.open_time
        existing = trader.positions.get(symbol)
        strategy_ids = {active.strategy_id}
        if existing:
            strategy_ids.add(existing.strategy_id)
        context = {}
        if strategy_ids & {"S04", "S06"}:
            context = await client.get_market_context(symbol, include_order_book="S04" in strategy_ids)

        if existing:
            exit_strategy = get_strategy(existing.strategy_id)
            if exit_strategy:
                reason = exit_strategy.should_exit(existing, candles_5m, candles_15m, context)
                await trader.process_strategy_candle(symbol, exit_strategy, latest, reason)
        if symbol not in trader.positions:
            signal = active.evaluate(symbol, candles_5m, candles_15m, context)
            if signal:
                await trader.open(signal)

    async def _position_loop(self, client, trader) -> None:
        while not self.stop_event.is_set():
            symbols = list(trader.positions)
            if symbols:
                prices = await asyncio.gather(*(client.get_mark_price(symbol) for symbol in symbols), return_exceptions=True)
                for symbol, price in zip(symbols, prices):
                    if isinstance(price, Exception):
                        logger.warning("mark price failed %s: %s", symbol, price)
                        continue
                    await trader.process_tick(symbol, price)
            await asyncio.sleep(self.settings.cycle_seconds)

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
