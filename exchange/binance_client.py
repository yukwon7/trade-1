from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from models import Candle

logger = logging.getLogger(__name__)


class BinanceFuturesClient:
    """Read-only Binance USD-M futures client with bounded concurrency and retry."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, api_key: str = "", concurrency: int = 6):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._semaphore = asyncio.Semaphore(concurrency)

    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> list[Candle]:
        payload = await self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": min(limit, 500)})
        candles = [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                quote_volume=float(row[7]),
            )
            for row in payload
        ]
        return candles[:-1] if len(candles) > 1 else candles

    async def get_mark_price(self, symbol: str) -> float:
        payload = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(payload["markPrice"])

    async def get_all_tickers(self) -> list[dict[str, Any]]:
        payload = await self._get("/fapi/v1/ticker/24hr")
        return payload if isinstance(payload, list) else []

    async def get_exchange_info(self) -> dict[str, Any]:
        payload = await self._get("/fapi/v1/exchangeInfo")
        return payload if isinstance(payload, dict) else {}

    async def get_historical_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
        output: dict[int, Candle] = {}
        cursor = start_ms
        while cursor < end_ms:
            payload = await self._get(
                "/fapi/v1/klines",
                {"symbol": symbol, "interval": interval, "limit": 1500, "startTime": cursor, "endTime": end_ms},
            )
            if not payload:
                break
            for row in payload:
                output[int(row[0])] = Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[7]))
            next_cursor = int(payload[-1][6]) + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            await asyncio.sleep(0.05)
        return sorted(output.values(), key=lambda item: item.open_time)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"X-MBX-APIKEY": self.api_key} if self.api_key else {}
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                async with self._semaphore:
                    async with self.session.get(
                        f"{self.base_url}{path}",
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as response:
                        if response.status in {418, 429} or response.status >= 500:
                            raise RuntimeError(f"Binance HTTP {response.status}")
                        response.raise_for_status()
                        return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                last_error = exc
                if attempt == 3:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError(f"Binance request failed: {path}: {last_error}")
