from __future__ import annotations

import asyncio
import logging
import signal as os_signal
import sys
from pathlib import Path

import aiohttp

from config import Settings
from notify.telegram_analysis_bot import TelegramAnalysisCommandHandler
from notify.telegram_notify import TelegramNotifier
from server_a.hermes.autonomy import post_autonomous_improvement
from server_a.hermes.env_manager import startup_env_check
from server_a.hermes.self_tuner import self_tune_loop


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/hermes.log", encoding="utf-8")],
    )


async def async_main() -> None:
    appended = await startup_env_check()
    settings = Settings.from_env()
    if settings.server_role != "analysis":
        raise RuntimeError("analysis bot requires SERVER_ROLE=analysis")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (os_signal.SIGINT, os_signal.SIGTERM):
        loop.add_signal_handler(name, stop_event.set)
    token = settings.telegram_analysis_bot_token or settings.telegram_bot_token
    chat_id = settings.telegram_analysis_chat_id or settings.telegram_chat_id
    async with aiohttp.ClientSession() as session:
        notifier = TelegramNotifier(session, token, chat_id)
        handler = TelegramAnalysisCommandHandler(session, token, chat_id, notifier, settings)
        await notifier.startup("analysis", len(settings.symbols), "Hermes AI orchestrator")
        if appended:
            await post_autonomous_improvement(notifier, ".env", f"startup appended optional keys: {','.join(appended)}")
        tune_task = asyncio.create_task(self_tune_loop(settings.config_dir, notifier), name="hermes-self-tune-loop")
        try:
            await handler.run(stop_event)
        finally:
            tune_task.cancel()
            await asyncio.gather(tune_task, return_exceptions=True)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(async_main())
