from __future__ import annotations

import asyncio
import logging
import signal as os_signal
import sys

from config import Settings
from execution.lightweight_trader import LightweightExecutionApplication


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def async_main() -> None:
    settings = Settings.from_env()
    if settings.server_role != "paper":
        raise RuntimeError("main.py is Server B execution-only and requires SERVER_ROLE=paper")
    application = LightweightExecutionApplication(settings)
    loop = asyncio.get_running_loop()
    for name in (os_signal.SIGINT, os_signal.SIGTERM):
        loop.add_signal_handler(name, application.stop_event.set)
    await application.run()


if __name__ == "__main__":
    setup_logging()
    asyncio.run(async_main())
