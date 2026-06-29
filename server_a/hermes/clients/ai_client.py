from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
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
    api_style: str = "openai"
    model_api_keys: dict[str, str] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.base_url and self.model and (self.api_key or self.model_api_keys))


class HermesAIClient:
    """Optional Server-A-only AI client.

    No provider is required.  If the relevant API key is absent, Hermes keeps
    using deterministic rule-based decisions.  This client returns suggestions
    only; deployment gates still validate every generated config.
    """

    def __init__(self, config: AIClientConfig):
        self.config = config

    @classmethod
    def from_env(cls, provider: str | None = None) -> "HermesAIClient":
        provider = (provider or os.getenv("HERMES_AI_PROVIDER", "")).strip().lower()
        if provider in {"glm", "glm4", "glm-4", "zhipu"}:
            return cls(AIClientConfig(
                provider="glm",
                api_key=os.getenv("GLM_API_KEY", "").strip(),
                base_url=os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
                model=os.getenv("GLM_MODEL", "glm-4-flash").strip(),
            ))
        if provider in {"gemini", "google"}:
            return cls(AIClientConfig(
                provider="gemini",
                api_key=os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip(),
                base_url=os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
                api_style="gemini",
            ))
        if provider in {"openrouter", "qwen", "qwen3"}:
            return cls(AIClientConfig(
                provider="openrouter",
                api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
                model=os.getenv("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b:free").strip(),
            ))
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
        if provider in {"grok", "xai"}:
            return cls(AIClientConfig(
                provider="grok",
                api_key=os.getenv("XAI_API_KEY", "").strip() or os.getenv("GROK_API_KEY", "").strip(),
                base_url=os.getenv("XAI_BASE_URL", os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")).rstrip("/"),
                model=os.getenv("GROK_MODEL", os.getenv("XAI_MODEL", "grok-3-mini")).strip(),
            ))
        if provider in {"nvidia", "nim", "nvidia_nim"}:
            model = os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-r1").strip()
            return cls(AIClientConfig(
                provider="nvidia",
                api_key=os.getenv("NVIDIA_API_KEY", "").strip() or os.getenv("NIM_API_KEY", "").strip(),
                base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
                model=model,
                model_api_keys=_nvidia_model_api_keys(model),
            ))
        return cls(AIClientConfig(provider="", api_key="", base_url="", model=""))

    async def suggest(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None
        return await self.complete_json(_system_prompt(), payload)

    async def complete_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None
        if self.config.api_style == "gemini":
            return await self._complete_json_gemini(system_prompt, payload)
        for model in _models(self.config.model):
            if self.config.provider == "nvidia" and _model_param("NVIDIA_MODEL_ENDPOINT", model, "").lower() == "responses":
                parsed = await self._complete_json_responses_model(model, system_prompt, payload)
                if parsed:
                    return parsed
                continue
            headers = self._headers_for_model(model)
            if not headers:
                logger.warning("Hermes AI model skipped because no API key is configured model=%s provider=%s", model, self.config.provider)
                continue
            body = self._chat_body(model, system_prompt, payload)
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

    def _headers_for_model(self, model: str) -> dict[str, str]:
        api_key = self.config.model_api_keys.get(model) or self.config.api_key
        if not api_key:
            return {}
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _chat_body(self, model: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": _model_float_param("NVIDIA_MODEL_TEMPERATURE", model, 0.1) if self.config.provider == "nvidia" else 0.1,
            "stream": False,
        }
        if self.config.provider == "nvidia":
            body["max_tokens"] = _model_int_param("NVIDIA_MODEL_MAX_TOKENS", model, int(os.getenv("NVIDIA_MAX_TOKENS", "4096")))
            body["top_p"] = _model_float_param("NVIDIA_MODEL_TOP_P", model, 1.0)
            top_k = _model_int_param("NVIDIA_MODEL_TOP_K", model, -1)
            if top_k >= 0:
                body["top_k"] = top_k
            repetition_penalty = _model_float_param("NVIDIA_MODEL_REPETITION_PENALTY", model, 0.0)
            if repetition_penalty > 0:
                body["repetition_penalty"] = repetition_penalty
            if _model_param("NVIDIA_MODEL_THINKING", model, "").lower() in {"false", "0", "off"}:
                body["chat_template_kwargs"] = {"thinking": False}
        else:
            body["response_format"] = {"type": "json_object"}
        return body

    async def _complete_json_responses_model(self, model: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = self._headers_for_model(model)
        if not headers:
            logger.warning("Hermes AI responses model skipped because no API key is configured model=%s provider=%s", model, self.config.provider)
            return None
        prompt = (
            f"{system_prompt}\n\n"
            "Return a single valid JSON object only.\n"
            f"Payload:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        body = {
            "model": model,
            "input": prompt,
            "max_output_tokens": _model_int_param("NVIDIA_MODEL_MAX_OUTPUT_TOKENS", model, 4096),
            "top_p": _model_float_param("NVIDIA_MODEL_TOP_P", model, 1.0),
            "temperature": _model_float_param("NVIDIA_MODEL_TEMPERATURE", model, 1.0),
            "stream": False,
        }
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.config.base_url}/responses",
                        headers=headers,
                        json=body,
                        timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds),
                    ) as response:
                        text = await response.text()
                        data = _parse_response_json(text)
                        if response.status != 200:
                            raise RuntimeError(f"AI HTTP {response.status}: {data}")
                        content = _extract_responses_text(data)
                        parsed = _parse_json_object(content)
                        parsed["_model_used"] = model
                        return parsed
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError, RuntimeError) as exc:
                logger.warning("Hermes AI responses failed model=%s attempt=%s provider=%s error=%s", model, attempt + 1, self.config.provider, exc)
                await asyncio.sleep(1 + attempt)
        return None

    async def _complete_json_gemini(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        prompt = (
            f"{system_prompt}\n\n"
            "Return a single valid JSON object only.\n"
            f"Payload:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        headers = {"Content-Type": "application/json"}
        for model in _models(self.config.model):
            body = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1},
            }
            url = f"{self.config.base_url}/models/{model}:generateContent?key={self.config.api_key}"
            for attempt in range(2):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            headers=headers,
                            json=body,
                            timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds),
                        ) as response:
                            text = await response.text()
                            data = _parse_response_json(text)
                            if response.status != 200:
                                raise RuntimeError(f"AI HTTP {response.status}: {data}")
                            content = data["candidates"][0]["content"]["parts"][0]["text"]
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


def _nvidia_model_api_keys(model_value: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for model in _models(model_value):
        api_key = _model_param("NVIDIA_MODEL_API_KEY", model, "")
        if api_key:
            keys[model] = api_key
    return keys


def _model_param(prefix: str, model: str, default: str) -> str:
    suffix = _model_env_suffix(model)
    return os.getenv(f"{prefix}_{suffix}", default).strip()


def _model_int_param(prefix: str, model: str, default: int) -> int:
    value = _model_param(prefix, model, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _model_float_param(prefix: str, model: str, default: float) -> float:
    value = _model_param(prefix, model, "")
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _model_env_suffix(model: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_").upper()
    return re.sub(r"_+", "_", suffix)


def _extract_responses_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    raise ValueError("responses output did not contain text")


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
