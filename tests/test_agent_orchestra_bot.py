from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace

from notify.telegram_analysis_bot import TelegramAnalysisCommandHandler
from server_a.hermes.agent_orchestra import AgentOrchestra


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


class AgentOrchestraBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notifier = FakeNotifier()
        settings = SimpleNamespace(project_dir=Path(self.tmp.name))
        self.old_allowed = os.environ.get("TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS")
        os.environ["TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS"] = "123"
        self.handler = TelegramAnalysisCommandHandler(None, "token", "123", self.notifier, settings)
        self.handler.agents = FakeAgents()

    async def asyncTearDown(self):
        if self.old_allowed is None:
            os.environ.pop("TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS", None)
        else:
            os.environ["TELEGRAM_ANALYSIS_ALLOWED_CHAT_IDS"] = self.old_allowed
        self.tmp.cleanup()

    async def test_agent_and_dev_commands(self):
        self.assertEqual(await self.handler.dispatch("agent", "hello"), "chat:hello")
        self.assertEqual(await self.handler.dispatch("dev", "fix tests"), "dev:fix tests")

    async def test_safe_commands(self):
        self.assertEqual(await self.handler.dispatch("git_status"), "safe:git_status")
        self.assertEqual(await self.handler.dispatch("run_tests"), "safe:tests")

    async def test_plain_text_routes_to_agent(self):
        update = {"message": {"chat": {"id": "123"}, "text": "안녕"}}
        await self.handler.handle_update(update)
        self.assertEqual(self.notifier.messages[-1], "chat:안녕")

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


if __name__ == "__main__":
    unittest.main()
