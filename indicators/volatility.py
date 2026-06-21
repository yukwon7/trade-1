from __future__ import annotations

from collections.abc import Sequence

from models import Candle


def atr(candles: Sequence[Candle], period: int = 14) -> list[float]:
    if not candles:
        return []
    true_ranges = [candles[0].high - candles[0].low]
    for current, previous in zip(candles[1:], candles[:-1]):
        true_ranges.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    output = [0.0] * len(true_ranges)
    seed_end = min(period, len(true_ranges))
    output[seed_end - 1] = sum(true_ranges[:seed_end]) / seed_end
    for index in range(seed_end, len(true_ranges)):
        output[index] = (output[index - 1] * (period - 1) + true_ranges[index]) / period
    return output
