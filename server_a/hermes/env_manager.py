from __future__ import annotations

import logging
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger("hermes.env")


STARTUP_ENV_DEFAULTS = {
    "AGENT_CONVERSATION_ENABLED": "true",
    "AGENT_MAX_ROUNDS": "3",
    "LOG_LEVEL": "INFO",
    "CACHE_TTL": "86400",
    "MAX_CONCURRENT_CONVERSATIONS": "2",
    "MAX_HISTORY_TURNS": "5",
    "GPT_MAX_TOKENS": "500",
    "GPT_TEMPERATURE": "0.3",
    "COMPRESSION_TARGET_TOKENS": "400",
    "RAM_WARN_MB": "200",
    "RAM_HARD_MB": "230",
    "MONITOR_DAILY_SUMMARY_HOUR_KST": "0",
}


def safe_append_env(key: str, value: str, env_path: str | Path = ".env") -> bool:
    """
    Append a new key to .env only if it does not already exist.
    Never overwrites. Never deletes. Append only.
    """
    path = Path(env_path)
    existing = dotenv_values(path)
    if key not in existing:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{key}={value}")
        return True
    return False


async def startup_env_check(env_path: str | Path = ".env") -> list[str]:
    """
    Check .env for missing optional keys and append defaults.
    Logs key names only, never values.
    """
    path = Path(env_path)
    existing = dotenv_values(path)
    appended: list[str] = []
    for key, default_value in STARTUP_ENV_DEFAULTS.items():
        if key not in existing and safe_append_env(key, default_value, path):
            appended.append(key)
    if appended:
        logger.info("[STARTUP] Appended missing keys: %s", appended)
        load_dotenv(path, override=True)
    else:
        logger.info("[STARTUP] .env check complete. No changes needed.")
    return appended
