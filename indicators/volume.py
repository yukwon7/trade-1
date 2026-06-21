from __future__ import annotations

from collections.abc import Sequence


def volume_ratio(volumes: Sequence[float], period: int = 20) -> list[float]:
    output = [0.0] * len(volumes)
    running = 0.0
    for index, value in enumerate(volumes):
        running += float(value)
        if index >= period:
            running -= float(volumes[index - period])
        count = min(index + 1, period)
        average = running / count if count else 0.0
        output[index] = float(value) / average if average > 0 else 0.0
    return output
