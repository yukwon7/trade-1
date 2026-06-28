from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

import aiohttp

from analytics.router_backtester import run_backtest
from analytics.stress_tester import run_stress_test, summary_text
from server_a.hermes.main import run_hermes_cycle

logger = logging.getLogger(__name__)


ANALYSIS_BOT_COMMANDS = [
    {"command": "analyze", "description": "run Hermes analysis cycle"},
    {"command": "daily", "description": "daily performance report"},
    {"command": "weekly", "description": "weekly performance report"},
    {"command": "monthly", "description": "monthly performance report"},
    {"command": "stress", "description": "run stress test"},
    {"command": "backtest", "description": "run stress-period backtest"},
    {"command": "strategies", "description": "strategy decision status"},
    {"command": "decision", "description": "latest Hermes decision"},
    {"command": "deploy_config", "description": "deploy generated config to Server B"},
    {"command": "rollback_config", "description": "rollback Server B config"},
    {"command": "hermes_status", "description": "Hermes status"},
]


class TelegramAnalysisCommandHandler:
    """Server A command bot. Heavy analysis is intentionally isolated here."""

    def __init__(self, session, token: str, chat_id: str, notifier, settings):
        self.session = session
        self.chat_id = str(chat_id)
        self.notifier = notifier
        self.settings = settings
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        configured = False
        backoff = 1
        while not stop_event.is_set():
            try:
                if not configured:
                    await self._api("deleteWebhook", {"drop_pending_updates": False})
                    await self._api("setMyCommands", {"commands": ANALYSIS_BOT_COMMANDS})
                    configured = True
                    logger.info("telegram analysis command polling started")
                result = await self._api(
                    "getUpdates", {"offset": self.offset, "timeout": 25, "allowed_updates": ["message"]}, timeout=35
                )
                for update in result:
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    await self.handle_update(update)
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("telegram analysis polling failed: %s", exc)
                configured = False
                await asyncio.sleep(backoff)
                backoff = min(30, backoff * 2)

    async def _api(self, method: str, payload: dict[str, Any], timeout: int = 15):
        async with self.session.post(
            f"{self.api_url}/{method}", json=payload, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed: HTTP {response.status} {data.get('description', '')}")
            return data.get("result")

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        text = message.get("text")
        if str((message.get("chat") or {}).get("id")) != self.chat_id or not isinstance(text, str) or not text.startswith("/"):
            return
        raw, _, argument = text.strip().partition(" ")
        command = raw[1:].split("@", 1)[0].lower()
        try:
            reply = await self.dispatch(command, argument.strip())
        except Exception:
            logger.exception("telegram analysis command failed: /%s", command)
            reply = "⚠️ 분석 명령 처리 중 오류가 발생했습니다. Server A 로그를 확인하세요."
        if reply:
            await self.notifier.send(reply[:4000])

    async def dispatch(self, command: str, argument: str = "") -> str:
        if command in {"start", "help", "hermes_status"}:
            return self.status_text()
        if command in {"analyze", "decision", "strategies"}:
            report = await asyncio.to_thread(run_hermes_cycle, self.settings, False)
            return "<pre>" + html.escape(report["summary"]) + "</pre>"
        if command == "stress":
            report = await asyncio.to_thread(run_stress_test, self.settings, False)
            return "<pre>" + html.escape(summary_text(report)) + "</pre>"
        if command == "backtest":
            report = await run_backtest(days=0, step=12, refresh=False, persist=False)
            return (
                "<pre>ROUTER_BACKTEST_STRESS_PERIOD\n"
                f"period={report['period_start']} -> {report['period_end']}\n"
                f"allowed={report['allowed_strategies']}</pre>"
            )
        if command in {"daily", "weekly", "monthly"}:
            report = await asyncio.to_thread(run_hermes_cycle, self.settings, False)
            return "<pre>" + html.escape(report["summary"]) + "</pre>"
        if command == "deploy_config":
            return "배포는 안전상 scripts/deploy_server_b_config_only.sh 로 실행하세요."
        if command == "rollback_config":
            return "롤백은 안전상 scripts/rollback_server_b_config.sh 로 실행하세요."
        return f"❓ 지원하지 않는 분석 명령입니다: /{html.escape(command)}"

    @staticmethod
    def status_text() -> str:
        return (
            "🧠 <b>Server A Hermes</b>\n"
            "/analyze /daily /weekly /monthly /stress /backtest\n"
            "/strategies /decision /deploy_config /rollback_config /hermes_status"
        )
