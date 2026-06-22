from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


TOURNAMENT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
)


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
    risk_per_trade: float = 0.02
    max_open_positions: int = 4
    max_leverage: int = 10
    fee_rate: float = 0.0004
    slippage: float = 0.0005
    candle_limit: int = 300
    cycle_seconds: int = 15
    tournament_mode: str = "MODE_B"
    symbols: tuple[str, ...] = field(default_factory=lambda: TOURNAMENT_SYMBOLS)

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
        if not token or not chat_id:
            raise ValueError("Telegram credentials must be present in .env")
        mode = os.getenv("TOURNAMENT_MODE", "MODE_B").strip().upper()
        if mode not in {"MODE_A", "MODE_B"}:
            mode = "MODE_B"
        return cls(
            server_role=role,
            project_dir=project_dir,
            data_dir=data_dir,
            config_dir=config_dir,
            database_path=Path(os.getenv("DATABASE_PATH", data_dir / "trades.db")).resolve(),
            binance_base_url=os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com").rstrip("/"),
            binance_api_key=os.getenv("BINANCE_API_KEY", "").strip(),
            binance_secret_key=os.getenv("BINANCE_SECRET_KEY", "").strip(),
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
            initial_balance=float(os.getenv("INITIAL_BALANCE", "1000")),
            # Tournament safety limits are code-enforced so stale values in the
            # preserved .env cannot silently weaken the new rules.
            risk_per_trade=0.02,
            max_open_positions=4,
            max_leverage=10,
            fee_rate=float(os.getenv("FEE_RATE", "0.0004")),
            slippage=float(os.getenv("SLIPPAGE", "0.0005")),
            candle_limit=min(500, max(120, int(os.getenv("CANDLE_LIMIT", "300")))),
            cycle_seconds=max(10, int(os.getenv("CYCLE_SECONDS", "15"))),
            tournament_mode=mode,
        )
