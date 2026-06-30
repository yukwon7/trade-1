from __future__ import annotations

import tempfile
import unittest
import os
import asyncio
from pathlib import Path
from types import SimpleNamespace

from notify.telegram_analysis_bot import ANALYSIS_BOT_COMMANDS, TelegramAnalysisCommandHandler
from server_a.hermes.agent_orchestra import AgentOrchestra
from server_a.hermes.agent_router import AgentRouter, _plan_agents


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, text):
        self.messages.append(text)


class FakeAgents:
    def __init__(self):
        self.cleared = False

    async def chat(self, message, mode="chat"):
        return f"{mode}:{message}"

    async def run_safe_command(self, name):
        return f"safe:{name}"

    def clear(self):
        self.cleared = True


class FakeRouter:
    def __init__(self):
        self.cleared = False

    async def auto(self, message):
        return f"auto:{message}"

    async def task(self, message):
        return f"task:{message}"

    async def debate(self, message):
        return f"debate:{message}"

    async def approve(self):
        return "approved"

    async def reject(self, reason):
        return f"rejected:{reason}"

    def stop(self):
        return "stopped"

    async def code(self, message):
        return f"code:{message}"

    async def think(self, message):
        return f"think:{message}"

    async def free(self, message):
        return f"free:{message}"

    async def premium(self, message):
        return f"premium:{message}"

    async def ask_provider(self, provider, message):
        return f"{provider}:{message}"

    async def review(self, message):
        return f"review:{message}"

    def models_text(self):
        return "models"

    def status_text(self):
        return "status"

    def cost_text(self):
        return "cost"

    def agents_text(self):
        return "agents"

    def clear(self):
        self.cleared = True


class FakeExecutor:
    def exec_status(self):
        return "exec_status"

    async def run(self, command, argument=""):
        return f"exec:{command}:{argument}"


class AgentOrchestraBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notifier = FakeNotifier()
        settings = SimpleNamespace(project_dir=Path(self.tmp.name))
        self.old_allowed = os.environ.get("TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS")
        os.environ["TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS"] = "123"
        self.handler = TelegramAnalysisCommandHandler(None, "token", "123", self.notifier, settings)
        self.handler.agents = FakeAgents()
        self.handler.router = FakeRouter()
        self.handler.executor = FakeExecutor()

    async def asyncTearDown(self):
        if self.old_allowed is None:
            os.environ.pop("TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS", None)
        else:
            os.environ["TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS"] = self.old_allowed
        self.tmp.cleanup()

    async def test_agent_and_dev_commands(self):
        self.assertEqual(await self.handler.dispatch("agent", "hello"), "auto:hello")
        self.assertEqual(await self.handler.dispatch("dev", "fix tests"), "code:fix tests")

    async def test_v4_master_commands(self):
        self.assertEqual(await self.handler.dispatch("task", "build feature"), "task:build feature")
        self.assertEqual(await self.handler.dispatch("debate", "architecture"), "debate:architecture")
        self.assertEqual(await self.handler.dispatch("approve"), "approved")
        self.assertEqual(await self.handler.dispatch("reject", "not enough"), "rejected:not enough")
        self.assertEqual(await self.handler.dispatch("stop"), "stopped")

    async def test_goal_command_starts_background_runner(self):
        async def fake_run_goal(chat_id, goal):
            self.handler.goal_state["progress"] = 100
            self.handler.goal_state["status"] = "완료"

        self.handler._run_goal = fake_run_goal
        reply = await self.handler.dispatch("goal", "새 기능 완성", "123")
        await asyncio.sleep(0)
        self.assertIn("목표 설정 완료", reply)
        self.assertIn("100%", await self.handler.dispatch("progress"))

    async def test_codex_command_enqueues_task(self):
        reply = await self.handler.dispatch("codex", "어려운 버그 고쳐줘")
        self.assertIn("Codex 작업 등록 완료", reply)
        self.assertIn("queued", self.handler.codex.status_text())

    async def test_goal_uses_codex_only_for_complex_work(self):
        self.handler.router.last_plan = SimpleNamespace(complexity="lean")
        self.handler.router.pending_task = SimpleNamespace(server_action="불필요")
        use_codex, reason = self.handler._should_use_codex("문구만 짧게 바꿔줘")
        self.assertFalse(use_codex)
        self.assertIn("간단한", reason)

        self.handler.router.last_plan = SimpleNamespace(complexity="deep")
        use_codex, reason = self.handler._should_use_codex("복잡한 코드 수정")
        self.assertTrue(use_codex)
        self.assertIn("deep", reason)

    async def test_goal_uses_codex_when_explicitly_requested(self):
        self.handler.router.last_plan = SimpleNamespace(complexity="lean")
        use_codex, reason = self.handler._should_use_codex("이건 코덱스로 최종 수정해줘")
        self.assertTrue(use_codex)
        self.assertIn("명시", reason)

    async def test_korean_menu_descriptions(self):
        descriptions = " ".join(item["description"] for item in ANALYSIS_BOT_COMMANDS)
        self.assertIn("목표", descriptions)
        self.assertIn("Codex", descriptions)
        self.assertIn("실행", descriptions)
        self.assertIn("진행", descriptions)
        self.assertIn("상태", descriptions)

    async def test_v3_router_commands(self):
        self.assertEqual(await self.handler.dispatch("think", "hello"), "think:hello")
        self.assertEqual(await self.handler.dispatch("free", "hello"), "free:hello")
        self.assertEqual(await self.handler.dispatch("gpt", "hello"), "premium:hello")
        self.assertEqual(await self.handler.dispatch("urgent", "hello"), "premium:hello")
        self.assertEqual(await self.handler.dispatch("nvidia", "hello"), "nvidia:hello")
        self.assertEqual(await self.handler.dispatch("code", "hello"), "code:hello")
        self.assertEqual(await self.handler.dispatch("review", "hello"), "review:hello")
        self.assertEqual(await self.handler.dispatch("model"), "models")
        self.assertEqual(await self.handler.dispatch("status"), "status")
        self.assertEqual(await self.handler.dispatch("cost"), "cost")
        self.assertEqual(await self.handler.dispatch("agents"), "agents")

    async def test_safe_commands(self):
        self.assertEqual(await self.handler.dispatch("git_status"), "exec:git_status:")
        self.assertEqual(await self.handler.dispatch("run_tests"), "exec:run_tests:")
        self.assertEqual(await self.handler.dispatch("server_status"), "exec:server_status:")
        self.assertEqual(await self.handler.dispatch("logs", "hermes-analysis-bot.service"), "exec:logs:hermes-analysis-bot.service")
        self.assertEqual(await self.handler.dispatch("exec_status"), "exec_status")

    async def test_plain_text_routes_to_agent(self):
        update = {"message": {"chat": {"id": "123"}, "text": "안녕"}}
        await self.handler.handle_update(update)
        self.assertEqual(self.notifier.messages[-1], "auto:안녕")

    async def test_bind_agent_room_registers_new_chat(self):
        sent = []

        async def fake_api(method, payload, timeout=15):
            sent.append((method, payload))
            return True

        self.handler._api = fake_api
        update = {"message": {"chat": {"id": "999", "type": "group", "title": "agent-room"}, "text": "/bind_agent_room"}}
        await self.handler.handle_update(update)
        self.assertEqual(sent[-1][0], "sendMessage")
        allowed_path = Path(self.tmp.name) / "config" / "analysis_allowed_chats.json"
        self.assertIn('"999"', allowed_path.read_text())
        self.assertTrue(self.handler._is_allowed_chat("999"))

    async def test_unbound_chat_is_ignored_until_bound(self):
        update = {"message": {"chat": {"id": "999"}, "text": "안녕"}}
        await self.handler.handle_update(update)
        self.assertEqual(self.notifier.messages, [])

    async def test_git_status_without_git_repo_is_explanatory(self):
        orchestra = AgentOrchestra(Path(self.tmp.name))
        reply = await orchestra.run_safe_command("git_status")
        self.assertIn("git checkout", reply)

    async def test_public_agent_text_hides_legacy_risk_personas(self):
        text = AgentRouter().agents_text().lower()
        self.assertNotIn("risk", text)
        self.assertNotIn("리스크", text)

    async def test_smart_agent_plan_uses_lean_team_for_simple_task(self):
        plan = _plan_agents("버튼 문구 하나 수정해줘", "feature")
        self.assertEqual(plan.complexity, "lean")
        self.assertLessEqual(len(plan.agents), 2)
        self.assertIn("ATHENA", plan.agents)

    async def test_smart_agent_plan_escalates_for_sensitive_task(self):
        plan = _plan_agents("Server B 배포와 API키 권한 변경을 검토해줘", "deploy")
        self.assertIn(plan.complexity, {"balanced", "deep"})
        self.assertIn("HEPHAESTUS", plan.agents)
        self.assertIn("ARES", plan.agents)

    async def test_smart_agent_plan_all_agents_when_requested(self):
        plan = _plan_agents("모든 에이전트가 전체 토론해줘", "architecture")
        self.assertTrue(plan.full_debate)
        self.assertGreaterEqual(len(plan.agents), 3)


if __name__ == "__main__":
    unittest.main()
