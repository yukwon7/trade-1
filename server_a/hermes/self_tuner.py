from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from server_a.hermes.autonomy import post_autonomous_improvement

logger = logging.getLogger("hermes.self_tune")

TUNABLE_KEYS = {
    "AGENT_MAX_ROUNDS",
    "MAX_CONCURRENT_CONVERSATIONS",
    "GPT_MAX_TOKENS",
    "GPT_TEMPERATURE",
    "COMPRESSION_TARGET_TOKENS",
    "RAM_WARN_MB",
    "CACHE_TTL",
}


async def get_6hour_stats(config_dir: str | Path = "config") -> dict[str, float]:
    path = Path(config_dir) / "hermes_metrics.json"
    defaults = {
        "queries": 0,
        "cache_hit_rate": 0.0,
        "gpt_skip_rate": 0.0,
        "avg_response_time": 0.0,
        "ram_warn_count": 0,
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    return {key: float(data.get(key, value)) for key, value in defaults.items()}


async def self_tune(config_dir: str | Path = "config", notifier=None, env_path: str | Path = ".env") -> dict[str, Any]:
    stats = await get_6hour_stats(config_dir)
    changes: list[tuple[str, str, str]] = []

    if stats["gpt_skip_rate"] > 0.90:
        changes.append(update_tunable("AGENT_MAX_ROUNDS", "2", env_path))

    if stats["ram_warn_count"] > 5:
        current = int(os.getenv("RAM_WARN_MB", "200"))
        changes.append(update_tunable("RAM_WARN_MB", str(max(150, current - 10)), env_path))

    if stats["cache_hit_rate"] > 0.80:
        changes.append(update_tunable("CACHE_TTL", "172800", env_path))

    if stats["avg_response_time"] > 8:
        changes.append(update_tunable("MAX_CONCURRENT_CONVERSATIONS", "1", env_path))

    report = format_tuning_report(stats, [item for item in changes if item[1] != item[2]])
    if notifier is not None:
        if any(before != after for _, before, after in changes):
            await post_autonomous_improvement(notifier, ".env", "runtime self tuning")
        await notifier.send(report)
    logger.info("[SELF-TUNE] stats=%s changed_keys=%s", stats, [key for key, before, after in changes if before != after])
    return {"stats": stats, "changes": changes, "report": report}


def update_tunable(key: str, value: str, env_path: str | Path = ".env") -> tuple[str, str, str]:
    if key not in TUNABLE_KEYS:
        raise ValueError(f"{key} is not tunable")
    path = Path(env_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    before = os.getenv(key, "")
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            current = line.split("=", 1)[1].strip()
            before = current
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"\n{key}={value}\n")
    path.write_text("".join(new_lines), encoding="utf-8")
    load_dotenv(path, override=True)
    logger.info("[SELF-TUNE] %s updated", key)
    return key, before, value


def format_tuning_report(stats: dict[str, float], changes: list[tuple[str, str, str]]) -> str:
    change_text = "\n".join(f"│   {key}: {before} → {after}" for key, before, after in changes) or "│   없음"
    return (
        "┌─────────────────────────────────┐\n"
        "│ 🔧 SELF-TUNE REPORT             │\n"
        "├─────────────────────────────────┤\n"
        "│ 📊 Last 6h stats:               │\n"
        f"│   Queries:        {int(stats['queries'])}\n"
        f"│   Cache hit:      {stats['cache_hit_rate'] * 100:.1f}%\n"
        f"│   GPT skip rate:  {stats['gpt_skip_rate'] * 100:.1f}%\n"
        f"│   Avg response:   {stats['avg_response_time']:.2f}s\n"
        f"│   RAM warns:      {int(stats['ram_warn_count'])} times\n"
        "│                                 │\n"
        "│ ⚙️ Changes made:                │\n"
        f"{change_text}\n"
        "│                                 │\n"
        "│ 🔮 Next tune in: 6h             │\n"
        "└─────────────────────────────────┘"
    )


async def self_tune_loop(config_dir: str | Path = "config", notifier=None, env_path: str | Path = ".env") -> None:
    while True:
        await asyncio.sleep(6 * 60 * 60)
        await self_tune(config_dir, notifier, env_path)
