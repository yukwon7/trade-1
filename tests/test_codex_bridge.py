from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
