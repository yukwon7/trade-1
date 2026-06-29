from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp

from analytics.router_backtester import run_backtest
from analytics.stress_tester import run_stress_test, summary_text
from server_a.hermes.agent_router import AgentRouter
from server_a.hermes.agent_orchestra import AgentOrchestra
from server_a.hermes.main import run_hermes_cycle_async

logger = logging.getLogger(__name__)


ANALYSIS_BOT_COMMANDS = [
    {"command": "start", "description": "initialize Hermes agent room"},
    {"command": "task", "description": "start development task"},
    {"command": "debate", "description": "summon agent debate"},
    {"command": "review", "description": "request code review"},
    {"command": "approve", "description": "approve pending consensus"},
    {"command": "reject", "description": "reject and rework"},
    {"command": "status", "description": "current Hermes state"},
    {"command": "agents", "description": "agent roles"},
    {"command": "stop", "description": "stop current work"},
    {"command": "bind_agent_room", "description": "bind this chat room"},
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
        self.agents = AgentOrchestra(settings.project_dir)
        self.router = AgentRouter()
        config_dir = Path(getattr(settings, "config_dir", Path(settings.project_dir) / "config"))
        self.allowed_chats_path = config_dir / "analysis_allowed_chats.json"

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
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not isinstance(text, str):
            return
        stripped = text.strip()
        raw_command = stripped.split(" ", 1)[0].split("@", 1)[0].lower() if stripped.startswith("/") else ""
        if not self._is_allowed_chat(chat_id):
            if raw_command == "/bind_agent_room":
                reply = self._bind_agent_room(chat_id)
                await self._send_to_chat(chat_id, reply)
                return
            logger.info(
                "ignored unauthorized analysis chat id=%s type=%s title=%s",
                chat_id,
                chat.get("type", ""),
                chat.get("title", ""),
            )
            return
        if not stripped.startswith("/"):
            if os.getenv("AGENT_CONVERSATION_ENABLED", "true").lower() != "true":
                return
            reply = await self.router.auto(stripped)
            await self._send_to_chat(chat_id, reply[:4000])
            return
        raw, _, argument = stripped.partition(" ")
        command = raw[1:].split("@", 1)[0].lower()
        try:
            reply = await self.dispatch(command, argument.strip())
        except Exception:
            logger.exception("telegram analysis command failed: /%s", command)
            reply = "⚠️ 분석 명령 처리 중 오류가 발생했습니다. Server A 로그를 확인하세요."
        if reply:
            await self._send_to_chat(chat_id, reply[:4000])

    async def _send_to_chat(self, chat_id: str, text: str) -> None:
        if chat_id == self.chat_id:
            await self.notifier.send(text)
            return
        await self._api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

    def _allowed_chat_ids(self) -> set[str]:
        raw = os.getenv("TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS", self.chat_id).strip()
        allowed = {item.strip() for item in raw.split(",") if item.strip()} if raw else {self.chat_id}
        if self.allowed_chats_path.exists():
            try:
                payload = json.loads(self.allowed_chats_path.read_text(encoding="utf-8"))
                allowed.update(str(item) for item in payload.get("chat_ids", []) if str(item).strip())
            except Exception as exc:
                logger.warning("failed to read allowed analysis chats: %s", exc)
        return allowed

    def _is_allowed_chat(self, chat_id: str) -> bool:
        allowed = self._allowed_chat_ids()
        return "*" in allowed or chat_id in allowed

    def _bind_agent_room(self, chat_id: str) -> str:
        allowed = self._allowed_chat_ids()
        if "*" in allowed or chat_id in allowed:
            return "이미 이 방은 Hermes AI 오케스트라 방으로 등록되어 있습니다."
        allowed.add(chat_id)
        self._write_allowed_chats(sorted(allowed))
        logger.info("bound telegram analysis room chat id=%s", chat_id)
        return (
            "✅ 이 방을 Hermes AI 오케스트라 방으로 등록했습니다.\n"
            "이제 일반 채팅은 AI 에이전트 대화로 처리되고, /dev 로 개발 요청을 보낼 수 있습니다."
        )

    def _write_allowed_chats(self, chat_ids: list[str]) -> None:
        self.allowed_chats_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chat_ids": chat_ids,
            "source": "telegram_bind_agent_room",
        }
        self.allowed_chats_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    async def dispatch(self, command: str, argument: str = "") -> str:
        if command in {"start", "help", "hermes_status"}:
            return self.status_text()
        if command == "task":
            return await self.router.task(argument or "마스터가 태스크 내용을 비워 보냈습니다. 필요한 작업을 질문해서 명확히 해라.")
        if command == "debate":
            return await self.router.debate(argument or "현재 Hermes 오케스트라 구조가 적절한지 토론해라.")
        if command == "approve":
            return await self.router.approve()
        if command == "reject":
            return await self.router.reject(argument)
        if command == "stop":
            self.agents.clear()
            return self.router.stop()
        if command in {"model", "models"}:
            return self.router.models_text()
        if command == "status":
            return self.router.status_text()
        if command == "cost":
            return self.router.cost_text()
        if command == "agents":
            return self.router.agents_text()
        if command in {"think"}:
            return await self.router.think(argument or "현재 상황을 교차검증해줘.")
        if command in {"free"}:
            return await self.router.free(argument or "현재 Hermes 상태를 요약해줘.")
        if command in {"gpt", "urgent"}:
            return await self.router.premium(argument or "중요 작업으로 판단하고 안전하게 검토해줘.")
        if command == "nvidia":
            return await self.router.ask_provider("nvidia", argument or "NVIDIA 모델 상태로 답변해줘.")
        if command == "code":
            return await self.router.code(argument or "현재 repo에서 다음 안전한 개발 작업을 제안해줘.")
        if command == "review":
            return await self.router.review(argument or "현재 코드 변경을 리뷰해줘.")
        if command in {"analyze", "decision", "strategies"}:
            report = await run_hermes_cycle_async(self.settings, False)
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
            report = await run_hermes_cycle_async(self.settings, False)
            return "<pre>" + html.escape(report["summary"]) + "</pre>"
        if command == "deploy_config":
            return "배포는 안전상 scripts/deploy_server_b_config_only.sh 로 실행하세요."
        if command == "rollback_config":
            return "롤백은 안전상 scripts/rollback_server_b_config.sh 로 실행하세요."
        if command in {"agent", "chat"}:
            return await self.router.auto(argument or "현재 Hermes 상태를 요약해줘.")
        if command == "dev":
            return await self.router.code(argument or "현재 repo에서 다음 안전한 개발 작업을 제안해줘.")
        if command == "git_status":
            return await self.agents.run_safe_command("git_status")
        if command == "run_tests":
            return await self.agents.run_safe_command("tests")
        if command == "clear":
            self.agents.clear()
            self.router.clear()
            return "대화 기록과 오케스트레이터 캐시를 초기화했습니다."
        return f"❓ 지원하지 않는 분석 명령입니다: /{html.escape(command)}"

    @staticmethod
    def status_text() -> str:
        return (
            "🔱 <b>HERMES AI 오케스트라</b>\n"
            "마스터 명령을 받아 전문 에이전트 토론 → 합의안 → 승인 대기로 진행합니다.\n"
            "/task 내용: 개발 태스크 시작\n"
            "/debate 주제: 전체 토론 소집\n"
            "/review 코드: 코드 리뷰\n"
            "/approve: 합의안 승인\n"
            "/reject 이유: 재작업\n"
            "/status: 현재 진행 상태\n"
            "/agents: 에이전트 역할 안내\n"
            "/stop: 전체 중단\n"
            "/bind_agent_room: 현재 방 등록\n"
            "일반 채팅도 HERMES가 태스크 여부를 판단해 처리합니다."
        )
