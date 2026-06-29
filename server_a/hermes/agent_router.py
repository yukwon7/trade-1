from __future__ import annotations

import hashlib
import html
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from server_a.hermes.agent_orchestra import AGENT_PERSONAS
from server_a.hermes.clients.ai_client import HermesAIClient


PROVIDER_ORDER = ("glm", "gemini", "openrouter", "openai", "nvidia")
ALL_PROVIDERS = ("glm", "gemini", "openrouter", "deepseek", "grok", "openai", "nvidia")

PROVIDER_ROLES = {
    "glm": "GLM-4-Flash: quick Korean draft, summary, light chat",
    "gemini": "Gemini Flash: code review, long-context verification",
    "openrouter": "Qwen/OpenRouter: reasoning, algorithms, tie-breaker",
    "deepseek": "DeepSeek: reasoning fallback when direct key is configured",
    "grok": "Grok/xAI: external reasoning fallback when configured",
    "openai": "OpenAI premium: final decision for important or urgent work",
    "nvidia": "NVIDIA NIM: high-performance fallback and large reasoning",
}

PREMIUM_KEYWORDS = (
    "봇", "전략", "서버", "배포", "보안", "api키", "손실", "긴급", "중요",
    "실서버", "아키텍처", "server b", "server a", "리팩터", "실거래",
)


@dataclass
class UsageCounter:
    requests: int = 0
    estimated_tokens: int = 0
    failures: int = 0
    last_used_at: str = ""


@dataclass
class AgentRouter:
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL", "1800")))
    cache: dict[str, tuple[float, str]] = field(default_factory=dict)
    usage: dict[str, UsageCounter] = field(default_factory=dict)

    async def auto(self, message: str) -> str:
        command = "code" if _looks_like_code_task(message) else "chat"
        if _needs_premium(message):
            return await self.premium(message, command)
        return await self.free(message, command)

    async def free(self, message: str, mode: str = "chat") -> str:
        return await self._ask_chain(("glm", "gemini", "openrouter", "nvidia"), message, mode)

    async def premium(self, message: str, mode: str = "urgent") -> str:
        return await self._ask_chain(("openai", "nvidia", "openrouter"), message, mode)

    async def ask_provider(self, provider: str, message: str, mode: str = "chat") -> str:
        return await self._ask_chain((provider,), message, mode)

    async def think(self, message: str, mode: str = "think") -> str:
        providers = ("glm", "gemini", "openrouter")
        results = []
        for provider in providers:
            result = await self._ask_one(provider, message, mode, use_cache=False)
            if result:
                results.append((provider, result))
        if not results:
            return await self._ask_chain(("nvidia", "openai"), message, mode)
        if len(results) == 1:
            return results[0][1]
        synthesis_payload = {
            "mode": "cross_verification_synthesis",
            "message": message[:3000],
            "agent_results": [{"provider": provider, "reply": reply[:1800]} for provider, reply in results],
            "instruction": "Synthesize the best final Korean answer. Return JSON only: reply, persona, suggested_commands.",
        }
        synthesis = await self._complete_with_provider("openrouter", synthesis_payload)
        if not synthesis:
            synthesis = await self._complete_with_provider("nvidia", synthesis_payload)
        if synthesis:
            return _format_reply("cross-check", synthesis, used=[p for p, _ in results])
        joined = "\n\n".join(f"[{provider}]\n{_strip_html(reply)}" for provider, reply in results)
        return f"🔍 교차검증 결과\n<pre>{html.escape(joined[:3500])}</pre>"

    async def review(self, message: str) -> str:
        return await self._ask_chain(("gemini", "openrouter", "nvidia"), message, "code_review")

    async def code(self, message: str) -> str:
        return await self._ask_chain(("gemini", "openrouter", "openai", "nvidia"), message, "code")

    def models_text(self) -> str:
        lines = ["🧠 <b>Hermes 모델 상태</b>"]
        for provider in ALL_PROVIDERS:
            client = HermesAIClient.from_env(provider)
            mark = "✓" if client.config.enabled else "—"
            model = client.config.model or "not configured"
            lines.append(f"{mark} {provider}: {html.escape(model)}")
        return "\n".join(lines)

    def agents_text(self) -> str:
        lines = ["🧩 <b>Hermes 에이전트 역할</b>"]
        for provider, role in PROVIDER_ROLES.items():
            client = HermesAIClient.from_env(provider)
            mark = "✓" if client.config.enabled else "—"
            lines.append(f"{mark} {provider}: {html.escape(role)}")
        return "\n".join(lines)

    def status_text(self) -> str:
        lines = ["📊 <b>Hermes Orchestrator Status</b>", self.models_text(), "", "오늘 프로세스 사용량:"]
        if not self.usage:
            lines.append("- 아직 호출 기록 없음")
        for provider, counter in sorted(self.usage.items()):
            lines.append(
                f"- {provider}: requests={counter.requests}, est_tokens={counter.estimated_tokens}, failures={counter.failures}"
            )
        return "\n".join(lines)

    def cost_text(self) -> str:
        openai = self.usage.get("openai", UsageCounter())
        nvidia = self.usage.get("nvidia", UsageCounter())
        return (
            "💰 <b>비용 보호 상태</b>\n"
            f"- OpenAI 추정 호출: {openai.requests}회 / 일일 제한 ${os.getenv('GPT_DAILY_LIMIT_USD', '5.0')}\n"
            f"- NVIDIA 추정 호출: {nvidia.requests}회 / 크레딧 제한 {os.getenv('NVIDIA_DAILY_CREDIT_LIMIT', '100')}\n"
            "- 실제 과금액은 provider 콘솔 기준입니다. Hermes는 키 값을 표시하지 않습니다."
        )

    def clear(self) -> None:
        self.cache.clear()

    async def _ask_chain(self, providers: tuple[str, ...], message: str, mode: str) -> str:
        cache_key = _cache_key(providers, message, mode)
        cached = self.cache.get(cache_key)
        if cached and time.time() - cached[0] < self.cache_ttl_seconds:
            return cached[1] + "\n\n<i>cache hit</i>"
        for provider in providers:
            reply = await self._ask_one(provider, message, mode, use_cache=False)
            if reply:
                self.cache[cache_key] = (time.time(), reply)
                return reply
        return "사용 가능한 AI provider가 없습니다. Server A `.env`에 GLM/Gemini/OpenRouter/OpenAI/NVIDIA/Grok 키 중 하나를 설정하세요."

    async def _ask_one(self, provider: str, message: str, mode: str, use_cache: bool = True) -> str:
        payload = {
            "mode": mode,
            "message": message[:6000],
            "personas": AGENT_PERSONAS,
            "provider_role": PROVIDER_ROLES.get(provider, provider),
            "constraints": [
                "Answer in natural Korean.",
                "Never reveal secrets or API key values.",
                "Server B changes require explicit user confirmation.",
                "Return JSON only with keys: reply, persona, suggested_commands.",
            ],
        }
        result = await self._complete_with_provider(provider, payload)
        if not result:
            return ""
        return _format_reply(provider, result)

    async def _complete_with_provider(self, provider: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        client = HermesAIClient.from_env(provider)
        if not client.config.enabled:
            return None
        self._record(provider, payload, failed=False)
        result = await client.complete_json(_orchestra_system_prompt(), payload)
        if not result:
            self._record(provider, {}, failed=True)
            return None
        result["_provider_used"] = provider
        return result

    def _record(self, provider: str, payload: dict[str, Any], failed: bool) -> None:
        counter = self.usage.setdefault(provider, UsageCounter())
        if failed:
            counter.failures += 1
        else:
            counter.requests += 1
            counter.estimated_tokens += max(1, len(str(payload)) // 4)
            counter.last_used_at = datetime.now(timezone.utc).isoformat()


def _orchestra_system_prompt() -> str:
    return (
        "You are Hermes AI Orchestrator on Server A. Coordinate AI agent roles for safe Korean responses. "
        "Do not output markdown tables unless requested. Do not expose secrets. "
        "Never modify Server B or claim deployment without explicit user approval and external execution. "
        "Return strict JSON with keys: reply, persona, suggested_commands."
    )


def _format_reply(provider: str, result: dict[str, Any], used: list[str] | None = None) -> str:
    reply = str(result.get("reply") or result.get("reason") or "응답이 비어 있습니다.")[:3500]
    persona = str(result.get("persona") or provider)
    commands = result.get("suggested_commands") or []
    extra = ""
    if commands:
        extra += "\n\n제안 명령:\n" + "\n".join(f"- {cmd}" for cmd in commands[:5])
    source = "+".join(used) if used else str(result.get("_provider_used") or provider)
    return f"🤖 <b>{html.escape(persona)}</b> <i>{html.escape(source)}</i>\n{html.escape(reply + extra)}"


def _cache_key(providers: tuple[str, ...], message: str, mode: str) -> str:
    raw = "|".join(providers) + "|" + mode + "|" + message.strip().lower()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _needs_premium(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in PREMIUM_KEYWORDS)


def _looks_like_code_task(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in ("코드", "버그", "테스트", "함수", "파일", "리팩터", "patch", "python"))


def _strip_html(text: str) -> str:
    return text.replace("<br>", "\n").replace("<pre>", "").replace("</pre>", "")
