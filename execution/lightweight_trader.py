from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import logging
import time

import aiohttp

from config import Settings
from exchange import BinanceFuturesClient
from execution.config_reloader import ConfigReloader, ExecutionRuntimeConfig
from execution.risk_engine import ExecutionRiskEngine
from notify.telegram_execution_bot import TelegramExecutionCommandHandler
from notify.telegram_notify import TelegramNotifier
from storage import SQLiteManager, TradeStore
from strategies import get_strategy, normalize_strategy_id
from trader import PaperTrader

logger = logging.getLogger("trade1.executor")


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


class LightweightExecutionApplication:
    """Server B runtime: market execution loop only."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.stop_event = asyncio.Event()
        self.last_processed: dict[str, int] = {}
        self.reloader = ConfigReloader(settings.config_dir, settings.symbols)

    async def run(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.config_dir.mkdir(parents=True, exist_ok=True)
        manager = SQLiteManager(self.settings.database_path)
        await manager.initialize()
        store = TradeStore(manager)
        connector = aiohttp.TCPConnector(limit=16, ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=connector) as session:
            client = BinanceFuturesClient(session, self.settings.binance_base_url, self.settings.binance_api_key)
            notifier = TelegramNotifier(session, self.settings.telegram_bot_token, self.settings.telegram_chat_id)
            trader = PaperTrader(self.settings, store, notifier)
            await trader.initialize()
            runtime = self.reloader.reload()
            trader.update_runtime_limits(runtime.risk)
            commands = TelegramExecutionCommandHandler(
                session, self.settings.telegram_bot_token, self.settings.telegram_chat_id,
                notifier, trader, store, self.reloader,
            )
            cache = CandleCache(client, self.settings.candle_limit)
            await notifier.startup("executor", len(runtime.symbols.symbols), ",".join(runtime.strategy.active_strategy_ids))
            tasks = [
                asyncio.create_task(self._signal_loop(client, cache, trader), name="execution-signal-loop"),
                asyncio.create_task(self._position_loop(client, trader), name="execution-position-loop"),
                asyncio.create_task(commands.run(self.stop_event), name="telegram-execution-loop"),
            ]
            await self.stop_event.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await manager.close()

    async def _signal_loop(self, client, cache, trader) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            runtime = self.reloader.reload()
            trader.update_runtime_limits(runtime.risk)
            strategies = self._active_strategies(runtime)
            symbols = runtime.symbols.symbols
            results = await asyncio.gather(
                *(self._analyze_symbol(symbol, strategies, runtime, cache, trader) for symbol in symbols),
                return_exceptions=True,
            )
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    logger.error("execution cycle failed %s: %s", symbol, result)
            outcomes = Counter(str(item) for item in results if not isinstance(item, Exception))
            logger.info(
                "execution cycle: strategies=%s symbols=%d outcomes=%s open_positions=%d",
                [strategy.strategy_id for strategy in strategies],
                len(symbols),
                dict(outcomes),
                len(trader.positions),
            )
            self._write_health_snapshot(runtime, outcomes, trader)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(5.0, self._seconds_to_next_five_minute() - elapsed))

    def _active_strategies(self, runtime: ExecutionRuntimeConfig):
        if runtime.strategy.mode == "paused":
            return []
        disabled = {normalize_strategy_id(item) for item in runtime.strategy.disabled_strategy_ids}
        output = []
        for strategy_id in runtime.strategy.active_strategy_ids:
            normalized = normalize_strategy_id(strategy_id)
            if normalized in disabled:
                continue
            strategy = get_strategy(normalized)
            if strategy is not None:
                output.append(strategy)
        if not output and not disabled:
            fallback = get_strategy("S99")
            if fallback is not None:
                output.append(fallback)
        return output[:3]

    async def _analyze_symbol(self, symbol, strategies, runtime, cache, trader) -> str:
        candles_5m, candles_15m = await asyncio.gather(cache.refresh(symbol, "5m"), cache.refresh(symbol, "15m"))
        if min(len(candles_5m), len(candles_15m)) < 100:
            return "INSUFFICIENT_DATA"
        latest = candles_5m[-1]
        if self.last_processed.get(symbol) == latest.open_time:
            return "ALREADY_PROCESSED"
        self.last_processed[symbol] = latest.open_time
        existing = trader.positions.get(symbol)
        context = {}
        if existing:
            exit_strategy = get_strategy(existing.strategy_id)
            if exit_strategy:
                reason = exit_strategy.should_exit(existing, candles_5m, candles_15m, context)
                await trader.process_strategy_candle(symbol, exit_strategy, latest, reason)
        if symbol in trader.positions:
            return "POSITION_MANAGED"
        risk = ExecutionRiskEngine(runtime)
        for strategy in strategies:
            signal = strategy.evaluate(symbol, candles_5m, candles_15m, context)
            if not signal:
                continue
            signal = risk.filter_signal(signal)
            if signal is None:
                return "SIGNAL_FILTERED"
            opened = await trader.open(signal)
            return "OPENED" if opened else "SIGNAL_BLOCKED"
        return "NO_SIGNAL"

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

    def _write_health_snapshot(self, runtime, outcomes, trader) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "active_strategy_ids": list(runtime.strategy.active_strategy_ids),
            "symbols": list(runtime.symbols.symbols),
            "risk": {
                "max_open_positions": runtime.risk.max_open_positions,
                "risk_per_trade": runtime.risk.risk_per_trade,
                "max_leverage": runtime.risk.max_leverage,
            },
            "config_errors": dict(self.reloader.last_errors),
            "outcomes": dict(outcomes),
            "open_positions": len(trader.positions),
        }
        path = self.settings.config_dir / "execution_health.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
