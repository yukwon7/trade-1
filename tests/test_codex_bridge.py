from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server_a.hermes.codex_bridge import CodexBridge


class CodexBridgeTests(unittest.TestCase):
    def test_enqueue_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = CodexBridge(Path(tmp) / "config", Path(tmp))
            task = bridge.enqueue("테스트 작업", "unit")
            self.assertEqual(task["status"], "queued")
            text = bridge.status_text()
            self.assertIn(task["id"], text)
            self.assertIn("테스트 작업", text)

    def test_run_once_blocks_when_direct_run_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = CodexBridge(Path(tmp) / "config", Path(tmp))
            bridge.enqueue("테스트 작업", "unit")
            with patch.dict(os.environ, {"HERMES_CODEX_DIRECT_RUN": "false"}, clear=False):
                result = bridge.run_once()
            self.assertEqual(result["status"], "blocked")
            self.assertIn("HERMES_CODEX_DIRECT_RUN", result["error"])

    def test_run_once_blocks_when_auth_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = CodexBridge(Path(tmp) / "config", Path(tmp))
            bridge.enqueue("테스트 작업", "unit")
            completed = Mock(returncode=1, stdout="No Codex credentials found", stderr="")
            with patch.dict(os.environ, {"HERMES_CODEX_DIRECT_RUN": "true"}, clear=False):
                with patch("server_a.hermes.codex_bridge.shutil.which", return_value="/usr/bin/codex"):
                    with patch("server_a.hermes.codex_bridge.subprocess.run", return_value=completed):
                        result = bridge.run_once()
            self.assertEqual(result["status"], "blocked")
            self.assertIn("authentication", result["error"])

    def test_diagnostic_text_reports_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = CodexBridge(Path(tmp) / "config", Path(tmp))
            completed = Mock(returncode=0, stdout="ok", stderr="")
            with patch.dict(os.environ, {"HERMES_CODEX_DIRECT_RUN": "true"}, clear=False):
                with patch("server_a.hermes.codex_bridge.shutil.which", return_value="/usr/bin/codex"):
                    with patch("server_a.hermes.codex_bridge.subprocess.run", return_value=completed):
                        text = bridge.diagnostic_text()
            self.assertIn("직접 실행: 켜짐", text)
            self.assertIn("인증: 인증됨", text)

    def test_run_once_uses_current_codex_exec_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = CodexBridge(Path(tmp) / "config", Path(tmp))
            bridge.enqueue("테스트 작업", "unit")
            doctor = Mock(returncode=0, stdout="ok", stderr="")
            exec_result = Mock(returncode=0, stdout="done", stderr="")
            with patch.dict(os.environ, {"HERMES_CODEX_DIRECT_RUN": "true"}, clear=False):
                with patch("server_a.hermes.codex_bridge.shutil.which", return_value="/usr/bin/codex"):
                    with patch(
                        "server_a.hermes.codex_bridge.subprocess.run",
                        side_effect=[doctor, exec_result],
                    ) as run:
                        result = bridge.run_once()
            self.assertEqual(result["status"], "done")
            command = run.call_args_list[1].args[0]
            self.assertIn("-c", command)
            self.assertIn('approval_policy="never"', command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertNotIn("--ask-for-approval", command)


if __name__ == "__main__":
    unittest.main()
