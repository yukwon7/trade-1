from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True, frozen=True)
class Settings:
    server_role: str
    project_dir: Path
    data_dir: Path
    config_dir: Path
    database_path: Path
    binance_base_url: str
    binance_api_key: str
    binance_secret_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    initial_balance: float = 1000.0
    risk_per_trade: float = 0.01
    min_score: int = 65
    max_leverage: int = 5
    max_open_positions: int = 5
    pyramiding_enabled: bool = True
    trade_frequency_multiplier: float = 1.0
    fee_rate: float = 0.0004
    slippage: float = 0.0005
    candle_limit: int = 500
    cycle_seconds: int = 30
    symbol_hard_cap: int = 15
    symbols: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SYMBOLS)
    symbol_blacklist: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        env_path = Path(env_file or os.getenv("ENV_FILE", ".env")).resolve()
        load_dotenv(env_path, override=False)
        project_dir = Path(os.getenv("PROJECT_DIR", env_path.parent)).resolve()
        data_dir = Path(os.getenv("DATA_DIR", project_dir / "data")).resolve()
        config_dir = Path(os.getenv("CONFIG_DIR", project_dir / "config")).resolve()
        role = os.getenv("SERVER_ROLE", "").strip().lower()
        if role not in {"paper", "analysis"}:
            raise ValueError("SERVER_ROLE must be 'paper' or 'analysis'")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        secret = os.getenv("BINANCE_SECRET_KEY", "").strip()
        if not token or not chat_id:
            raise ValueError("Telegram credentials must be present in .env")
        return cls(
            server_role=role,
            project_dir=project_dir,
            data_dir=data_dir,
            config_dir=config_dir,
            database_path=Path(os.getenv("DATABASE_PATH", data_dir / "trades.db")).resolve(),
            binance_base_url=os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com").rstrip("/"),
            binance_api_key=api_key,
            binance_secret_key=secret,
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
            initial_balance=float(os.getenv("INITIAL_BALANCE", "1000")),
            risk_per_trade=float(os.getenv("RISK_PER_TRADE", "0.01")),
            min_score=int(os.getenv("MIN_SCORE", "65")),
            max_leverage=int(os.getenv("MAX_LEVERAGE", "5")),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "5")),
            pyramiding_enabled=_env_bool("PYRAMIDING_ENABLED", True),
            fee_rate=float(os.getenv("FEE_RATE", "0.0004")),
            slippage=float(os.getenv("SLIPPAGE", "0.0005")),
            candle_limit=min(500, int(os.getenv("CANDLE_LIMIT", "500"))),
            cycle_seconds=max(10, int(os.getenv("CYCLE_SECONDS", "30"))),
        )


class RuntimeConfig:
    """Hot-reloads optimizer overrides and scanner-selected symbols by mtime."""

    ALLOWED_OVERRIDES = {
        "MIN_SCORE": "min_score",
        "MAX_LEVERAGE": "max_leverage",
        "TRADE_FREQUENCY_MULTIPLIER": "trade_frequency_multiplier",
        "PYRAMIDING_ENABLED": "pyramiding_enabled",
        "SYMBOL_BLACKLIST": "symbol_blacklist",
    }

    def __init__(self, base: Settings):
        self.base = base
        self.current = base
        self._mtimes: dict[Path, int] = {}

    def reload(self) -> Settings:
        overrides = self.base.config_dir / "config_override.json"
        selected = self.base.config_dir / "selected_symbols.json"
        if not self._changed(overrides) and not self._changed(selected):
            return self.current
        values: dict[str, Any] = {}
        override_data = self._read_json(overrides)
        for external, internal in self.ALLOWED_OVERRIDES.items():
            if external in override_data:
                values[internal] = override_data[external]
        symbol_data = self._read_json(selected)
        symbols = symbol_data.get("symbols", list(self.base.symbols))
        if not isinstance(symbols, list):
            symbols = list(self.base.symbols)
        clean = tuple(dict.fromkeys(str(x).upper() for x in symbols if str(x).endswith("USDT")))
        values["symbols"] = clean[: self.base.symbol_hard_cap] or self.base.symbols
        if "symbol_blacklist" in values:
            raw_blacklist = values["symbol_blacklist"] if isinstance(values["symbol_blacklist"], list) else []
            values["symbol_blacklist"] = tuple(str(item).upper() for item in raw_blacklist)
        values["min_score"] = max(65, min(95, int(values.get("min_score", self.base.min_score))))
        values["max_leverage"] = max(1, min(5, int(values.get("max_leverage", self.base.max_leverage))))
        values["trade_frequency_multiplier"] = max(0.1, min(1.0, float(values.get("trade_frequency_multiplier", 1.0))))
        if "pyramiding_enabled" in values and not isinstance(values["pyramiding_enabled"], bool):
            values["pyramiding_enabled"] = self.base.pyramiding_enabled
        self.current = replace(self.base, **values)
        logger.info("runtime configuration reloaded: symbols=%d min_score=%d max_leverage=%d", len(self.current.symbols), self.current.min_score, self.current.max_leverage)
        return self.current

    def _changed(self, path: Path) -> bool:
        mtime = path.stat().st_mtime_ns if path.exists() else 0
        changed = self._mtimes.get(path) != mtime
        self._mtimes[path] = mtime
        return changed

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("invalid runtime config %s: %s", path, exc)
            return {}
