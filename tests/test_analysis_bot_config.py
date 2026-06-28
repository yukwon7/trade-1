from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings


class AnalysisBotConfigTests(unittest.TestCase):
    def test_analysis_bot_token_falls_back_to_execution_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {
                "SERVER_ROLE": "analysis",
                "PROJECT_DIR": tmp,
                "TELEGRAM_BOT_TOKEN": "main-token",
                "TELEGRAM_CHAT_ID": "123",
            }, clear=False):
                settings = Settings.from_env(env)
        self.assertEqual(settings.telegram_analysis_bot_token, "main-token")
        self.assertEqual(settings.telegram_analysis_chat_id, "123")

    def test_analysis_bot_token_can_be_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {
                "SERVER_ROLE": "analysis",
                "PROJECT_DIR": tmp,
                "TELEGRAM_BOT_TOKEN": "main-token",
                "TELEGRAM_CHAT_ID": "123",
                "TELEGRAM_ANALYSIS_BOT_TOKEN": "analysis-token",
                "TELEGRAM_ANALYSIS_CHAT_ID": "456",
            }, clear=False):
                settings = Settings.from_env(env)
        self.assertEqual(settings.telegram_analysis_bot_token, "analysis-token")
        self.assertEqual(settings.telegram_analysis_chat_id, "456")


if __name__ == "__main__":
    unittest.main()
