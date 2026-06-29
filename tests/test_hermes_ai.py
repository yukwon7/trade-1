from __future__ import annotations

import unittest
from unittest.mock import patch

from server_a.hermes.clients.ai_client import AIClientConfig, HermesAIClient, _parse_json_object
from server_a.hermes.gate import deployment_gate
from server_a.hermes.orchestrator import apply_ai_suggestion


class FakeAIClient(HermesAIClient):
    def __init__(self, suggestion):
        super().__init__(AIClientConfig("deepseek", "key", "http://example.invalid", "model"))
        self.suggestion = suggestion

    async def suggest(self, payload):
        return self.suggestion


class HermesAITests(unittest.IsolatedAsyncioTestCase):
    def test_nvidia_provider_reads_env(self):
        with patch.dict("os.environ", {
            "HERMES_AI_PROVIDER": "nvidia",
            "NVIDIA_API_KEY": "test-key",
            "NVIDIA_MODEL": "nvidia/test-model",
        }, clear=False):
            client = HermesAIClient.from_env()
        self.assertTrue(client.config.enabled)
        self.assertEqual(client.config.provider, "nvidia")
        self.assertEqual(client.config.base_url, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(client.config.model, "nvidia/test-model")

    def test_v3_providers_read_env(self):
        env = {
            "GLM_API_KEY": "glm-key",
            "GEMINI_API_KEY": "gemini-key",
            "OPENROUTER_API_KEY": "or-key",
            "XAI_API_KEY": "xai-key",
        }
        with patch.dict("os.environ", env, clear=False):
            self.assertTrue(HermesAIClient.from_env("glm").config.enabled)
            gemini = HermesAIClient.from_env("gemini").config
            self.assertTrue(gemini.enabled)
            self.assertEqual(gemini.api_style, "gemini")
            self.assertEqual(HermesAIClient.from_env("openrouter").config.provider, "openrouter")
            self.assertEqual(HermesAIClient.from_env("grok").config.provider, "grok")

    def test_ai_json_parser_extracts_object_from_reasoning_text(self):
        parsed = _parse_json_object('thinking...\\n{"action":"KEEP","reason":"ok"}\\nfinal')
        self.assertEqual(parsed["action"], "KEEP")

    async def test_no_provider_keeps_rule_based_decision(self):
        report = {
            "performance": {},
            "decision": {
                "action": "KEEP",
                "reason": "rule",
                "strategy_config": {"active_strategy_ids": ["MACD_RSI_MOMENTUM"], "mode": "auto"},
                "risk_config": {"risk_per_trade": 0.01, "max_leverage": 3, "max_open_positions": 3},
            },
            "deployable": True,
            "gate_reason": "ok",
        }
        result = await apply_ai_suggestion(report, HermesAIClient(AIClientConfig("", "", "", "")))
        self.assertFalse(result["ai"]["used"])
        self.assertEqual(result["decision"]["action"], "KEEP")

    async def test_ai_risk_increase_is_clamped(self):
        report = {
            "performance": {},
            "decision": {
                "action": "KEEP",
                "reason": "rule",
                "strategy_config": {"active_strategy_ids": ["MACD_RSI_MOMENTUM"], "mode": "auto"},
                "risk_config": {"risk_per_trade": 0.01, "max_leverage": 3, "max_open_positions": 3},
            },
            "deployable": True,
            "gate_reason": "ok",
        }
        result = await apply_ai_suggestion(report, FakeAIClient({
            "action": "REDUCE_RISK",
            "reason": "test",
            "risk_config": {"risk_per_trade": 0.5, "max_leverage": 20, "max_open_positions": 10},
        }))
        risk = result["decision"]["risk_config"]
        self.assertEqual(risk["risk_per_trade"], 0.01)
        self.assertEqual(risk["max_leverage"], 3)
        self.assertEqual(risk["max_open_positions"], 3)
        allowed, reason = deployment_gate(result["decision"])
        self.assertTrue(allowed, reason)

    async def test_ai_cannot_downgrade_disable_to_keep(self):
        report = {
            "performance": {},
            "decision": {
                "action": "DISABLE_STRATEGY",
                "reason": "rule",
                "strategy_config": {"active_strategy_ids": ["MACD_RSI_MOMENTUM"], "mode": "paused"},
                "risk_config": {"risk_per_trade": 0.01, "max_leverage": 3, "max_open_positions": 3},
            },
            "deployable": True,
            "gate_reason": "ok",
        }
        result = await apply_ai_suggestion(report, FakeAIClient({"action": "KEEP", "reason": "too optimistic"}))
        self.assertEqual(result["decision"]["action"], "DISABLE_STRATEGY")


if __name__ == "__main__":
    unittest.main()
