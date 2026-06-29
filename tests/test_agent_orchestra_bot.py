from __future__ import annotations

import tempfile
import unittest
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
        self.handler = TelegramAnalysisCommandHandler(None, "token", "123", self.notifier, settings)
        self.handler.agents = FakeAgents()

    async def asyncTearDown(self):
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

    async def test_git_status_without_git_repo_is_explanatory(self):
        orchestra = AgentOrchestra(Path(self.tmp.name))
        reply = await orchestra.run_safe_command("git_status")
        self.assertIn("git checkout", reply)


if __name__ == "__main__":
    unittest.main()
