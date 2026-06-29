from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

from server_a.hermes.env_manager import startup_env_check
from server_a.hermes.self_tuner import self_tune, update_tunable


class EnvSelfTuneTests(unittest.TestCase):
    def test_startup_env_check_appends_missing_defaults_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("AGENT_MAX_ROUNDS=9\nTELEGRAM_BOT_TOKEN=secret\n", encoding="utf-8")
            appended = asyncio.run(startup_env_check(env))
            values = dotenv_values(env)
        self.assertNotIn("AGENT_MAX_ROUNDS", appended)
        self.assertEqual(values["AGENT_MAX_ROUNDS"], "9")
        self.assertEqual(values["AGENT_CONVERSATION_ENABLED"], "true")
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "secret")

    def test_update_tunable_rewrites_only_allowed_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("RAM_WARN_MB=200\nSECRET_KEY=keep\n", encoding="utf-8")
            with patch.dict(os.environ, {"RAM_WARN_MB": "200"}, clear=False):
                update_tunable("RAM_WARN_MB", "190", env)
            values = dotenv_values(env)
        self.assertEqual(values["RAM_WARN_MB"], "190")
        self.assertEqual(values["SECRET_KEY"], "keep")

    def test_self_tune_uses_metrics_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / ".env"
            env.write_text("AGENT_MAX_ROUNDS=3\nCACHE_TTL=86400\nRAM_WARN_MB=200\nMAX_CONCURRENT_CONVERSATIONS=2\n", encoding="utf-8")
            config = root / "config"
            config.mkdir()
            (config / "hermes_metrics.json").write_text(
                '{"queries":10,"cache_hit_rate":0.9,"gpt_skip_rate":0.95,"avg_response_time":9,"ram_warn_count":6}',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"RAM_WARN_MB": "200"}, clear=False):
                result = asyncio.run(self_tune(config, None, env))
            values = dotenv_values(env)
        self.assertIn("SELF-TUNE REPORT", result["report"])
        self.assertEqual(values["AGENT_MAX_ROUNDS"], "2")
        self.assertEqual(values["CACHE_TTL"], "172800")
        self.assertEqual(values["MAX_CONCURRENT_CONVERSATIONS"], "1")
        self.assertEqual(values["RAM_WARN_MB"], "190")


if __name__ == "__main__":
    unittest.main()
