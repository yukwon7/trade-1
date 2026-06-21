from __future__ import annotations

from collections.abc import Sequence

from models import Candle


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
    return output


def adx(candles: Sequence[Candle], period: int = 14) -> list[float]:
    count = len(candles)
    if count == 0:
        return []
    tr = [0.0] * count
    plus_dm = [0.0] * count
    minus_dm = [0.0] * count
    for index in range(1, count):
        current, previous = candles[index], candles[index - 1]
        up = current.high - previous.high
        down = previous.low - current.low
        plus_dm[index] = up if up > down and up > 0 else 0.0
        minus_dm[index] = down if down > up and down > 0 else 0.0
        tr[index] = max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close))
    atr_values = _wilder(tr, period)
    plus = _wilder(plus_dm, period)
    minus = _wilder(minus_dm, period)
    dx: list[float] = []
    for a, p, m in zip(atr_values, plus, minus):
        if a <= 0:
            dx.append(0.0)
            continue
        pdi, mdi = 100.0 * p / a, 100.0 * m / a
        total = pdi + mdi
        dx.append(0.0 if total == 0 else 100.0 * abs(pdi - mdi) / total)
    return _wilder(dx, period)


def _wilder(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    output = [0.0] * len(values)
    seed_end = min(period, len(values))
    output[seed_end - 1] = sum(values[:seed_end]) / seed_end
    for index in range(seed_end, len(values)):
        output[index] = (output[index - 1] * (period - 1) + values[index]) / period
    return output
