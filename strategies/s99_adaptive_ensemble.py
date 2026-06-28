from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from strategies.base import BaseStrategy


DEFAULT_EXCLUDED = {"S04", "S06", "S99"}


class AdaptiveEnsembleStrategy(BaseStrategy):
    strategy_id = "S99"
    name = "ADAPTIVE_ENSEMBLE"
    leverage = 3
    stop_loss_pct = 0.008
    take_profit_pct = 0.015
    minimum_candles = 120

    def __init__(self, config_path: str | Path = "config/adaptive_ensemble.json"):
        self.config_path = Path(config_path)

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if min(len(candles_5m), len(candles_15m)) < self.minimum_candles:
            return None
        config = self._load_config()
        if symbol in set(config.get("symbol_blacklist", [])):
            return None
        allowed_symbols = set(config.get("symbol_allowlist") or [])
        if allowed_symbols and symbol not in allowed_symbols:
            return None

        votes = []
        from strategies.registry import STRATEGIES

        allowed = set(config.get("allowed_strategies") or [])
        excluded = DEFAULT_EXCLUDED | set(config.get("excluded_strategies") or [])
        blocked_pairs = set(config.get("blocked_pairs") or [])
        for strategy_id, strategy in STRATEGIES.items():
            if strategy_id in excluded:
                continue
            if allowed and strategy_id not in allowed:
                continue
            signal = strategy.evaluate(symbol, candles_5m, candles_15m, context or {})
            if signal is None:
                continue
            pair_key = f"{strategy_id}:{symbol}:{signal.direction}"
            if pair_key in blocked_pairs:
                continue
            votes.append(signal)

        if not votes:
            return None
        direction_counts = Counter(signal.direction for signal in votes)
        direction, count = direction_counts.most_common(1)[0]
        opposing = sum(value for key, value in direction_counts.items() if key != direction)
        minimum_votes = int(config.get("minimum_votes", 2))
        if count < minimum_votes or opposing >= count:
            return None

        selected = [signal for signal in votes if signal.direction == direction]
        reasons = ", ".join(f"{signal.strategy_id}:{signal.reason}" for signal in selected[:4])
        metadata = {
            "votes": [signal.strategy_id for signal in selected],
            "vote_count": count,
            "opposing_votes": opposing,
            "source": "adaptive_ensemble",
        }
        return self.signal(symbol, direction, candles_5m[-1].close, f"ensemble vote {count}-{opposing}: {reasons}", metadata)

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        signal = self.evaluate(position.symbol, candles_5m, candles_15m, context or {})
        if signal and signal.direction != position.direction:
            return "ENSEMBLE_OPPOSITE_SIGNAL"
        return None

    def _load_config(self) -> dict:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
