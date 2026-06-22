from __future__ import annotations

import math
from collections.abc import Sequence

from indicators import ema, rsi
from models import Candle


def closes(candles: Sequence[Candle]) -> list[float]:
    return [item.close for item in candles]


def sma(values: Sequence[float], period: int) -> list[float]:
    output = [0.0] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += float(value)
        if index >= period:
            running -= float(values[index - period])
        count = min(index + 1, period)
        output[index] = running / count
    return output


def bollinger(values: Sequence[float], period: int = 20, deviations: float = 2.0):
    middle = sma(values, period)
    upper, lower, width = [], [], []
    for index, value in enumerate(values):
        window = values[max(0, index - period + 1) : index + 1]
        mean = middle[index]
        variance = sum((float(item) - mean) ** 2 for item in window) / len(window)
        sigma = math.sqrt(variance)
        upper.append(mean + deviations * sigma)
        lower.append(mean - deviations * sigma)
        width.append((upper[-1] - lower[-1]) / mean if mean else 0.0)
    return middle, upper, lower, width


def macd(values: Sequence[float]):
    fast, slow = ema(values, 12), ema(values, 26)
    line = [left - right for left, right in zip(fast, slow)]
    signal = ema(line, 9)
    histogram = [left - right for left, right in zip(line, signal)]
    return line, signal, histogram


def heikin_ashi(candles: Sequence[Candle]):
    ha_open: list[float] = []
    ha_close: list[float] = []
    for index, candle in enumerate(candles):
        close = (candle.open + candle.high + candle.low + candle.close) / 4.0
        opening = (candle.open + candle.close) / 2.0 if index == 0 else (ha_open[-1] + ha_close[-1]) / 2.0
        ha_open.append(opening)
        ha_close.append(close)
    return ha_open, ha_close


def rolling_vwap(candles: Sequence[Candle], period: int = 96) -> list[float]:
    output: list[float] = []
    pv: list[float] = []
    volumes: list[float] = []
    for candle in candles:
        typical = (candle.high + candle.low + candle.close) / 3.0
        pv.append(typical * candle.volume)
        volumes.append(candle.volume)
        start = max(0, len(pv) - period)
        total_volume = sum(volumes[start:])
        output.append(sum(pv[start:]) / total_volume if total_volume else candle.close)
    return output


def range_mid(candles: Sequence[Candle]) -> float:
    return (max(item.high for item in candles) + min(item.low for item in candles)) / 2.0


def ichimoku_cloud(candles: Sequence[Candle], index: int = -1) -> tuple[float, float, float, float]:
    actual = len(candles) + index if index < 0 else index
    if actual < 77:
        raise ValueError("at least 78 candles required")
    conversion = range_mid(candles[actual - 8 : actual + 1])
    base = range_mid(candles[actual - 25 : actual + 1])
    source = actual - 26
    source_conversion = range_mid(candles[source - 8 : source + 1])
    source_base = range_mid(candles[source - 25 : source + 1])
    span_a = (source_conversion + source_base) / 2.0
    span_b = range_mid(candles[source - 51 : source + 1])
    return conversion, base, min(span_a, span_b), max(span_a, span_b)


def rsi_values(candles: Sequence[Candle]) -> list[float]:
    return rsi(closes(candles), 14)
