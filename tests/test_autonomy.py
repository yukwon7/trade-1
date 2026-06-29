from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from server_a.hermes.autonomy import append_changelog, post_autonomous_improvement


class AutonomyTests(unittest.TestCase):
    def test_append_changelog_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CHANGELOG.md"
            append_changelog("file.py", "reason", "changed", path)
            text = path.read_text(encoding="utf-8")
        self.assertIn("[AUTONOMOUS]", text)
        self.assertIn("file.py", text)
        self.assertIn("reason", text)

    def test_post_autonomous_improvement(self):
        class Notifier:
            def __init__(self):
                self.messages = []

            async def send(self, text):
                self.messages.append(text)

        notifier = Notifier()
        asyncio.run(post_autonomous_improvement(notifier, "file.py", "better"))
        self.assertIn("자율 개선", notifier.messages[0])


if __name__ == "__main__":
    unittest.main()
