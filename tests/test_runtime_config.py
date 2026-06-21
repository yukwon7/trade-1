import json
import tempfile
import unittest
from pathlib import Path

from config import RuntimeConfig, Settings


class RuntimeConfigTests(unittest.TestCase):
    def test_hot_reload_caps_symbols_and_leverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir = root / "config"
            config_dir.mkdir()
            settings = Settings(
                server_role="paper", project_dir=root, data_dir=root / "data", config_dir=config_dir,
                database_path=root / "data/trades.db", binance_base_url="https://example.test",
                binance_api_key="", binance_secret_key="", telegram_bot_token="x", telegram_chat_id="1",
            )
            (config_dir / "config_override.json").write_text(json.dumps({"MIN_SCORE": 70, "MAX_LEVERAGE": 99}))
            symbols = [f"COIN{i}USDT" for i in range(20)]
            (config_dir / "selected_symbols.json").write_text(json.dumps({"symbols": symbols}))
            current = RuntimeConfig(settings).reload()
            self.assertEqual(current.min_score, 70)
            self.assertEqual(current.max_leverage, 5)
            self.assertEqual(len(current.symbols), 15)


if __name__ == "__main__":
    unittest.main()
