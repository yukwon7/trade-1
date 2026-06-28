from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AIClientConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 45

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.api_key and self.base_url and self.model)


class HermesAIClient:
    """Optional Server-A-only AI client.

    No provider is required.  If the relevant API key is absent, Hermes keeps
    using deterministic rule-based decisions.  This client returns suggestions
    only; deployment gates still validate every generated config.
    """

    def __init__(self, config: AIClientConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "HermesAIClient":
        provider = os.getenv("HERMES_AI_PROVIDER", "").strip().lower()
        if provider == "deepseek":
            return cls(AIClientConfig(
                provider="deepseek",
                api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            ))
        if provider == "openai":
            return cls(AIClientConfig(
                provider="openai",
                api_key=os.getenv("OPENAI_API_KEY", "").strip(),
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
            ))
        if provider in {"nvidia", "nim", "nvidia_nim"}:
            return cls(AIClientConfig(
                provider="nvidia",
                api_key=os.getenv("NVIDIA_API_KEY", "").strip() or os.getenv("NIM_API_KEY", "").strip(),
                base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
                model=os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-r1").strip(),
            ))
        return cls(AIClientConfig(provider="", api_key="", base_url="", model=""))

    async def suggest(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        for model in _models(self.config.model):
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
                ],
                "temperature": 0.1,
                "stream": False,
                "response_format": {"type": "json_object"},
            }
            for attempt in range(2):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{self.config.base_url}/chat/completions",
                            headers=headers,
                            json=body,
                            timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds),
                        ) as response:
                            text = await response.text()
                            data = _parse_response_json(text)
                            if response.status != 200:
                                raise RuntimeError(f"AI HTTP {response.status}: {data}")
                            content = data["choices"][0]["message"]["content"]
                            parsed = _parse_json_object(content)
                            parsed["_model_used"] = model
                            return parsed
                except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError, RuntimeError) as exc:
                    logger.warning("Hermes AI suggestion failed model=%s attempt=%s provider=%s error=%s", model, attempt + 1, self.config.provider, exc)
                    await asyncio.sleep(1 + attempt)
        return None


def _system_prompt() -> str:
    return (
        "You are Hermes, a Server-A-only trading-system analyst. "
        "You never trade and never request secrets. "
        "Return strict JSON with optional keys: action, reason, strategy_config, risk_config. "
        "Never increase max_leverage above 3, risk_per_trade above 0.01, or max_open_positions above 3. "
        "If evidence is weak, prefer KEEP, TUNE_PARAMETERS, DISABLE_STRATEGY, or REDUCE_RISK."
    )


def _models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("AI response did not contain a JSON object")


def _parse_response_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            chunks.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    if chunks:
        return chunks[-1]
    raise ValueError("AI HTTP response did not contain JSON")
