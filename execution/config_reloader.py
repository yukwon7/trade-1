from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_STRATEGY_IDS = ("S99",)
DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
)


class ConfigValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StrategyExecutionConfig:
    active_strategy_ids: tuple[str, ...] = DEFAULT_STRATEGY_IDS
    disabled_strategy_ids: tuple[str, ...] = ()
    mode: str = "auto"
    min_score: float = 65.0
    updated_at: str = ""
    reason: str = "default"


@dataclass(frozen=True, slots=True)
class RiskExecutionConfig:
    max_open_positions: int = 3
    risk_per_trade: float = 0.01
    max_leverage: int = 3
    daily_loss_limit: float = 0.03
    weekly_drawdown_limit: float = 0.08
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class SymbolExecutionConfig:
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    updated_at: str = ""
    source: str = "default"


@dataclass(frozen=True, slots=True)
class ExecutionRuntimeConfig:
    strategy: StrategyExecutionConfig
    risk: RiskExecutionConfig
    symbols: SymbolExecutionConfig
    loaded_at: str


class ConfigReloader:
    """Hot-reload lightweight execution config for Server B.

    Validation is fail-closed per file: invalid updates are rejected and the
    previous valid config remains active.  This keeps Server B stable when
    Server A publishes malformed or partial files.
    """

    def __init__(self, config_dir: str | Path, default_symbols: tuple[str, ...] = DEFAULT_SYMBOLS):
        self.config_dir = Path(config_dir)
        self._default_symbols = tuple(default_symbols)[:10] or DEFAULT_SYMBOLS
        self._strategy = StrategyExecutionConfig()
        self._risk = RiskExecutionConfig()
        self._symbols = SymbolExecutionConfig(symbols=self._default_symbols)
        self._file_signatures: dict[str, tuple[int, int]] = {}
        self.last_errors: dict[str, str] = {}

    def current(self) -> ExecutionRuntimeConfig:
        return ExecutionRuntimeConfig(
            strategy=self._strategy,
            risk=self._risk,
            symbols=self._symbols,
            loaded_at=datetime.now(timezone.utc).isoformat(),
        )

    def reload(self) -> ExecutionRuntimeConfig:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._strategy = self._reload_one("strategy_config.json", self._strategy, self._parse_strategy)
        self._risk = self._reload_one("risk_config.json", self._risk, self._parse_risk)
        self._symbols = self._reload_one("selected_symbols.json", self._symbols, self._parse_symbols)
        return self.current()

    def _reload_one(self, filename: str, previous, parser):
        path = self.config_dir / filename
        if not path.exists():
            return previous
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if self._file_signatures.get(filename) == signature:
            return previous
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            parsed = parser(data)
        except (OSError, json.JSONDecodeError, ConfigValidationError, TypeError, ValueError) as exc:
            self.last_errors[filename] = str(exc)
            logger.warning("rejected invalid execution config %s: %s", path, exc)
            return previous
        self._file_signatures[filename] = signature
        self.last_errors.pop(filename, None)
        logger.info("loaded execution config %s", path)
        return parsed

    @staticmethod
    def _parse_strategy(data: dict[str, Any]) -> StrategyExecutionConfig:
        if not isinstance(data, dict):
            raise ConfigValidationError("strategy_config must be an object")
        active = _string_tuple(data.get("active_strategy_ids", DEFAULT_STRATEGY_IDS), "active_strategy_ids")
        disabled = _string_tuple(data.get("disabled_strategy_ids", ()), "disabled_strategy_ids")
        if len(active) > 3:
            raise ConfigValidationError("active_strategy_ids supports at most 3 strategies on Server B")
        mode = str(data.get("mode", "auto")).lower()
        if mode not in {"auto", "manual", "paused"}:
            raise ConfigValidationError("mode must be auto, manual, or paused")
        min_score = float(data.get("min_score", 65))
        if not 0 <= min_score <= 100:
            raise ConfigValidationError("min_score must be between 0 and 100")
        return StrategyExecutionConfig(
            active_strategy_ids=active or DEFAULT_STRATEGY_IDS,
            disabled_strategy_ids=disabled,
            mode=mode,
            min_score=min_score,
            updated_at=str(data.get("updated_at", "")),
            reason=str(data.get("reason", "")),
        )

    @staticmethod
    def _parse_risk(data: dict[str, Any]) -> RiskExecutionConfig:
        if not isinstance(data, dict):
            raise ConfigValidationError("risk_config must be an object")
        max_open = int(data.get("max_open_positions", 3))
        risk = float(data.get("risk_per_trade", 0.01))
        leverage = int(data.get("max_leverage", 3))
        daily = float(data.get("daily_loss_limit", 0.03))
        weekly = float(data.get("weekly_drawdown_limit", 0.08))
        if not 1 <= max_open <= 5:
            raise ConfigValidationError("max_open_positions must be between 1 and 5")
        if not 0 < risk <= 0.02:
            raise ConfigValidationError("risk_per_trade must be >0 and <=0.02")
        if not 1 <= leverage <= 3:
            raise ConfigValidationError("max_leverage must be between 1 and 3")
        if not 0 < daily <= 0.10:
            raise ConfigValidationError("daily_loss_limit must be >0 and <=0.10")
        if not 0 < weekly <= 0.20:
            raise ConfigValidationError("weekly_drawdown_limit must be >0 and <=0.20")
        return RiskExecutionConfig(max_open, risk, leverage, daily, weekly, str(data.get("updated_at", "")))

    def _parse_symbols(self, data: dict[str, Any]) -> SymbolExecutionConfig:
        if not isinstance(data, dict):
            raise ConfigValidationError("selected_symbols must be an object")
        symbols = _string_tuple(data.get("symbols", self._default_symbols), "symbols")
        if not symbols:
            raise ConfigValidationError("symbols cannot be empty")
        normalized = tuple(symbol.upper() for symbol in symbols if symbol.upper().endswith("USDT"))
        if not normalized:
            raise ConfigValidationError("symbols must contain USDT pairs")
        return SymbolExecutionConfig(
            symbols=normalized[:10],
            updated_at=str(data.get("updated_at", "")),
            source=str(data.get("source", "")),
        )


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = list(value)
    else:
        raise ConfigValidationError(f"{field} must be a string list")
    output = tuple(str(item).strip().upper() for item in items if str(item).strip())
    if len(set(output)) != len(output):
        raise ConfigValidationError(f"{field} contains duplicate values")
    return output
