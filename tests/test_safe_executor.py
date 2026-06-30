from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server_a.hermes.safe_executor import SafeExecutor


class SafeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_exec_status_reports_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = SafeExecutor(Path(tmp)).exec_status()
            self.assertIn("실행 상태", text)

    async def test_exec_status_reports_codex_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = Mock(returncode=1, stdout="No Codex credentials found", stderr="")
            with patch("server_a.hermes.safe_executor.shutil.which") as which:
                which.side_effect = lambda name: f"/usr/bin/{name}"
                with patch("server_a.hermes.safe_executor.subprocess.run", return_value=completed):
                    text = SafeExecutor(Path(tmp)).exec_status()
            self.assertIn("인증 필요", text)

    async def test_rejects_unknown_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = await SafeExecutor(Path(tmp)).run("rm_rf")
            self.assertIn("지원하지 않는", text)


if __name__ == "__main__":
    unittest.main()
