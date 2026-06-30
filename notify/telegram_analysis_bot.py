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
from server_a.hermes.codex_bridge import CodexBridge
from server_a.hermes.main import run_hermes_cycle_async
from server_a.hermes.safe_executor import SafeExecutor

logger = logging.getLogger(__name__)


ANALYSIS_BOT_COMMANDS = [
    {"command": "start", "description": "헤르메스 시작/도움말"},
    {"command": "goal", "description": "목표 설정 후 진행 보고"},
    {"command": "progress", "description": "현재 목표 진행률"},
    {"command": "codex", "description": "Codex 작업 등록"},
    {"command": "codex_status", "description": "Codex 작업 상태"},
    {"command": "exec_status", "description": "실행 가능 상태"},
    {"command": "server_status", "description": "서버 상태 조회"},
    {"command": "run_tests", "description": "테스트 실행"},
    {"command": "logs", "description": "헤르메스 로그 조회"},
    {"command": "task", "description": "개발 태스크 시작"},
    {"command": "debate", "description": "에이전트 토론"},
    {"command": "review", "description": "코드 리뷰"},
    {"command": "approve", "description": "합의안 승인"},
    {"command": "reject", "description": "거부/재작업"},
    {"command": "status", "description": "현재 상태"},
    {"command": "agents", "description": "에이전트 목록"},
    {"command": "stop", "description": "중단"},
    {"command": "bind_agent_room", "description": "현재 방 등록"},
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
        self.config_dir = config_dir
        self.codex = CodexBridge(config_dir, Path(settings.project_dir))
        self.executor = SafeExecutor(Path(settings.project_dir))
        self.allowed_chats_path = config_dir / "analysis_allowed_chats.json"
        self.goal_task: asyncio.Task | None = None
        self.goal_state: dict[str, Any] = {}

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
            reply = await self.dispatch(command, argument.strip(), chat_id)
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

    async def dispatch(self, command: str, argument: str = "", chat_id: str | None = None) -> str:
        if command in {"start", "help", "hermes_status", "시작", "도움말"}:
            return self.status_text()
        if command in {"goal", "목표", "set_goal"}:
            return self.start_goal(chat_id or self.chat_id, argument)
        if command in {"progress", "goal_status", "진행", "진행률"}:
            return self.goal_status_text()
        if command in {"codex", "코덱스"}:
            return self.codex_enqueue(argument)
        if command in {"codex_status", "코덱스상태"}:
            return self.codex.status_text(argument)
        if command in {"codex_run", "코덱스실행"}:
            task = self.codex.run_once()
            return f"Codex worker: {html.escape(str(task.get('status')))}\n{html.escape(str(task.get('error') or task.get('message') or task.get('result') or '')[:1200])}"
        if command in {"exec_status", "실행상태"}:
            return self.executor.exec_status()
        if command in {"server_status", "서버상태"}:
            return await self.executor.run("server_status")
        if command in {"logs", "로그"}:
            return await self.executor.run("logs", argument)
        if command in {"task", "작업"}:
            return await self.router.task(argument or "마스터가 태스크 내용을 비워 보냈습니다. 필요한 작업을 질문해서 명확히 해라.")
        if command in {"debate", "토론"}:
            return await self.router.debate(argument or "현재 Hermes 오케스트라 구조가 적절한지 토론해라.")
        if command in {"approve", "승인"}:
            return await self.router.approve()
        if command in {"reject", "거절", "반려"}:
            return await self.router.reject(argument)
        if command in {"stop", "중단"}:
            self.agents.clear()
            self.stop_goal()
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
            return await self.executor.run("git_status")
        if command == "run_tests":
            return await self.executor.run("run_tests")
        if command == "clear":
            self.agents.clear()
            self.router.clear()
            self.stop_goal()
            return "대화 기록과 오케스트레이터 캐시를 초기화했습니다."
        return f"❓ 지원하지 않는 분석 명령입니다: /{html.escape(command)}"

    def start_goal(self, chat_id: str, goal: str) -> str:
        goal = goal.strip()
        if not goal:
            return "사용법: /goal 목표내용"
        if self.goal_task and not self.goal_task.done():
            return "이미 진행 중인 목표가 있습니다. /progress 로 확인하거나 /stop 으로 중단하세요."
        self.goal_state = {
            "goal": goal,
            "progress": 0,
            "status": "시작",
            "started_at": asyncio.get_running_loop().time(),
        }
        self.goal_task = asyncio.create_task(self._run_goal(chat_id, goal))
        return f"🎯 목표 설정 완료\n진행률 0%\n{html.escape(goal[:700])}"

    def stop_goal(self) -> None:
        if self.goal_task and not self.goal_task.done():
            self.goal_task.cancel()
        if self.goal_state:
            self.goal_state["status"] = "중단"

    def goal_status_text(self) -> str:
        if not self.goal_state:
            return "진행 중인 목표가 없습니다. /goal 목표내용 으로 시작하세요."
        return (
            f"🎯 목표 진행률 {int(self.goal_state.get('progress', 0))}%\n"
            f"상태: {html.escape(str(self.goal_state.get('status', '대기')))}\n"
            f"목표: {html.escape(str(self.goal_state.get('goal', ''))[:700])}"
        )

    async def _run_goal(self, chat_id: str, goal: str) -> None:
        try:
            await self._goal_update(chat_id, 10, "목표 분석 중")
            await asyncio.sleep(0.2)
            await self._goal_update(chat_id, 40, "에이전트가 초안/실행안 작성 중")
            report = await self.router.task(goal)
            use_codex, reason = self._should_use_codex(goal)
            if use_codex:
                task = await self._append_goal_queue(goal, report)
                await self._goal_update(chat_id, 75, f"Codex 최종 개발 큐 등록 완료: {task['id']}")
            else:
                await self._goal_update(chat_id, 75, f"Codex 생략: {reason}")
            await self._send_to_chat(chat_id, _compact_text(report, 1600))
            done_text = "완료 — Codex가 최종 수정 대기" if use_codex else "완료 — 에이전트 합의안으로 충분"
            await self._goal_update(chat_id, 100, done_text)
        except asyncio.CancelledError:
            await self._goal_update(chat_id, int(self.goal_state.get("progress", 0)), "중단됨")
            raise
        except Exception:
            logger.exception("Hermes goal runner failed")
            await self._goal_update(chat_id, int(self.goal_state.get("progress", 0)), "오류 — Server A 로그 확인 필요")

    async def _goal_update(self, chat_id: str, progress: int, status: str) -> None:
        self.goal_state["progress"] = progress
        self.goal_state["status"] = status
        await self._send_to_chat(chat_id, f"🎯 목표 진행률 {progress}%\n{html.escape(status)}")

    def _should_use_codex(self, goal: str) -> tuple[bool, str]:
        lowered = goal.lower()
        if "codex" in lowered or "코덱스" in lowered:
            return True, "마스터가 Codex를 명시함"
        plan = self.router.last_plan
        pending = self.router.pending_task
        if plan and plan.complexity in {"deep", "full"}:
            return True, f"{plan.complexity} 복잡도"
        if pending and pending.server_action == "승인 필요":
            return True, "서버/배포 영향으로 승인 필요"
        code_words = ("구현", "개발", "수정", "고쳐", "패치", "리팩터", "파일", "코드")
        if plan and plan.complexity == "balanced" and any(word in lowered for word in code_words):
            return True, "중간 난도 코드 작업"
        return False, "간단한 작업은 에이전트 초안만 사용"

    async def _append_goal_queue(self, goal: str, report: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.codex.enqueue, goal, "telegram_goal", report[:3000])

    def codex_enqueue(self, prompt: str) -> str:
        prompt = prompt.strip()
        if not prompt:
            return "사용법: /codex Codex에게 맡길 작업"
        task = self.codex.enqueue(prompt, "telegram_codex")
        available = "가능" if self.codex.codex_available() else "Server A에 Codex CLI 없음"
        return (
            "🧩 Codex 작업 등록 완료\n"
            f"ID: {task['id']}\n"
            f"상태: {task['status']}\n"
            f"CLI: {available}\n"
            "확인: /codex_status"
        )

    @staticmethod
    def status_text() -> str:
        return (
            "🔱 <b>HERMES AI 오케스트라</b>\n"
            "짧게 답하고, 목표 모드에서는 진행률을 계속 보고합니다.\n"
            "/goal 목표: 끝까지 진행 보고\n"
            "/progress: 목표 진행률\n"
            "/codex 요청: Codex 작업 등록\n"
            "/codex_status: Codex 큐 확인\n"
            "/exec_status: 실행 가능 상태\n"
            "/server_status /run_tests /logs: 실제 실행\n"
            "/task 내용: 태스크 합의안\n"
            "/debate 주제: 에이전트 토론\n"
            "/review 코드: 코드 리뷰\n"
            "/approve /reject 이유: 승인/재작업\n"
            "/status /agents: 상태/목록\n"
            "/stop: 중단\n"
            "/bind_agent_room: 현재 방 등록"
        )


def _compact_text(text: str, limit: int = 1600) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n…요약 표시"
