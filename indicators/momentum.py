from __future__ import annotations

from collections.abc import Sequence


def rsi(values: Sequence[float], period: int = 14) -> list[float]:
    if not values:
        return []
    output = [50.0] * len(values)
    if len(values) <= period:
        return output
    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for index in range(1, len(values)):
        delta = float(values[index]) - float(values[index - 1])
        gains[index] = max(delta, 0.0)
        losses[index] = max(-delta, 0.0)
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    output[period] = _rsi_value(avg_gain, avg_loss)
    for index in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        output[index] = _rsi_value(avg_gain, avg_loss)
    return output


def _rsi_value(gain: float, loss: float) -> float:
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)
