from __future__ import annotations

from dataclasses import replace
from typing import Any

from execution.config_reloader import ExecutionRuntimeConfig
from models import StrategySignal
from strategies import normalize_strategy_id


class ExecutionRiskEngine:
    """Small Server-B risk filter.

    This does not analyze markets. It only enforces the active config against a
    candidate signal before the trader opens a paper/live-equivalent position.
    """

    def __init__(self, runtime: ExecutionRuntimeConfig):
        self.runtime = runtime

    def allowed_strategy_ids(self) -> set[str]:
        active = {normalize_strategy_id(item) for item in self.runtime.strategy.active_strategy_ids}
        disabled = {normalize_strategy_id(item) for item in self.runtime.strategy.disabled_strategy_ids}
        return active - disabled

    def filter_signal(self, signal: StrategySignal) -> StrategySignal | None:
        if self.runtime.strategy.mode == "paused":
            return None
        allowed = self.allowed_strategy_ids()
        if signal.strategy_id not in allowed and "S99" not in allowed:
            return None
        score = _score(signal.metadata)
        if score is not None and score < self.runtime.strategy.min_score:
            return None
        leverage = min(signal.leverage, self.runtime.risk.max_leverage)
        return replace(signal, leverage=leverage)


def _score(metadata: dict[str, Any]) -> float | None:
    value = metadata.get("score") if isinstance(metadata, dict) else None
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
