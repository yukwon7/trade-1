from __future__ import annotations

import asyncio
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
REPLY_MAX_CHARS = int(os.getenv("HERMES_REPLY_MAX_CHARS", "1200"))

PROVIDER_ROLES = {
    "glm": "GLM-4-Flash: quick Korean draft, summary, light chat",
    "gemini": "Gemini Flash: code review, long-context verification",
    "openrouter": "Qwen/OpenRouter: reasoning, algorithms, tie-breaker",
    "deepseek": "DeepSeek: reasoning fallback when direct key is configured",
    "grok": "Grok/xAI: external reasoning fallback when configured",
    "openai": "OpenAI premium: final decision for important or urgent work",
    "nvidia": "NVIDIA NIM: high-performance fallback and large reasoning",
}

@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    icon: str
    model: str
    role: str
    stance: str


AGENT_TEAM: dict[str, AgentSpec] = {
    "HERMES": AgentSpec(
        "HERMES",
        "🔱",
        "openai/gpt-oss-120b",
        "총괄 오케스트레이터 — 명령 해석, 태스크 분해, 배정, 중재, 최종 보고",
        "단일 실행안으로 수렴시킨다.",
    ),
    "ZEUS": AgentSpec(
        "ZEUS",
        "⚡",
        "deepseek-ai/deepseek-v4-pro",
        "아키텍처 & 설계 — 구조, 확장성, 유지보수성 검토",
        "빠른 구현보다 올바른 설계를 우선한다.",
    ),
    "ATHENA": AgentSpec(
        "ATHENA",
        "💻",
        "qwen/qwen3.5-397b-a17b",
        "풀스택 코드 구현 — 코드 작성, 리팩토링, 버그 수정",
        "구현 가능성과 실용성 중심으로 조율한다.",
    ),
    "APOLLO": AgentSpec(
        "APOLLO",
        "🔍",
        "deepseek-ai/deepseek-r1",
        "리서치 & 최적화 — 조사, 성능 분석, 베스트 프랙티스 제안",
        "데이터와 근거 중심으로 판단한다.",
    ),
    "ARES": AgentSpec(
        "ARES",
        "🛡",
        "z-ai/glm-5.1",
        "코드 리뷰 & 보안 검증 — 취약점, 엣지케이스, 병목 검토",
        "치명적 결함이 있으면 VETO한다.",
    ),
    "HEPHAESTUS": AgentSpec(
        "HEPHAESTUS",
        "🖥",
        "meta/llama-3.3-70b-instruct",
        "인프라 & 배포 — 서버 환경, 자동화, 롤백 계획",
        "운영 안정성과 복구 가능성을 우선한다.",
    ),
    "ORACLE": AgentSpec(
        "ORACLE",
        "🧪",
        "meta/llama-3.1-70b-instruct",
        "QA & 모니터링 — 테스트, 결과 검증, 사용자 관점 확인",
        "실제로 동작하는지를 최우선으로 본다.",
    ),
}

TASK_AGENTS = {
    "feature": ("ZEUS", "APOLLO", "ATHENA", "ARES", "ORACLE"),
    "bug": ("APOLLO", "ATHENA", "ARES", "ORACLE"),
    "architecture": ("ZEUS", "APOLLO", "ARES"),
    "review": ("ARES", "APOLLO", "ATHENA"),
    "deploy": ("HEPHAESTUS", "ARES", "ORACLE"),
    "research": ("APOLLO", "ZEUS", "ATHENA"),
    "automation": ("ATHENA", "HEPHAESTUS", "ORACLE"),
    "performance": ("APOLLO", "ATHENA", "ARES", "ORACLE"),
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
class PendingTask:
    task_id: str
    task_type: str
    message: str
    agents: tuple[str, ...]
    consensus: str
    ares_verdict: str
    server_action: str
    created_at: str


@dataclass
class AgentRouter:
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL", "1800")))
    cache: dict[str, tuple[float, str]] = field(default_factory=dict)
    usage: dict[str, UsageCounter] = field(default_factory=dict)
    pending_task: PendingTask | None = None

    async def auto(self, message: str) -> str:
        command = "code" if _looks_like_code_task(message) else "chat"
        if _needs_premium(message):
            return await self.task(message)
        if _looks_like_code_task(message):
            return await self.task(message)
        return await self._call_agent_text("HERMES", message, command)

    async def task(self, message: str) -> str:
        task_type = _classify_task(message)
        agents = TASK_AGENTS[task_type]
        return await self._run_workflow("task", message, agents, task_type)

    async def debate(self, topic: str) -> str:
        return await self._run_workflow("debate", topic, tuple(AGENT_TEAM.keys()), "architecture")

    async def approve(self) -> str:
        if not self.pending_task:
            return "승인 대기 중인 합의안이 없습니다. 먼저 /task 또는 /debate 를 실행하세요."
        task = self.pending_task
        self.pending_task = None
        return (
            "✅ 승인 접수\n"
            "━━━━━━━━━━━━━━━\n"
            f"📌 태스크: {html.escape(task.message[:500])}\n"
            f"🧭 합의안: {html.escape(task.consensus[:1200])}\n"
            f"🖥 서버 실행: {html.escape(task.server_action)}\n"
            "━━━━━━━━━━━━━━━\n"
            "현재 Telegram 오케스트레이터는 임의 코드 수정/배포를 직접 실행하지 않습니다. "
            "승인된 합의안은 Codex 작업 세션에서 패치·테스트·배포 절차로 이어서 처리합니다."
        )

    async def reject(self, reason: str) -> str:
        if not self.pending_task:
            return "재작업할 승인 대기 합의안이 없습니다."
        old = self.pending_task
        self.pending_task = None
        if reason:
            return await self.task(f"기존 합의안을 거부하고 재작업한다. 거부 사유: {reason}. 원 태스크: {old.message}")
        return "합의안을 폐기했습니다. 새 /task 명령으로 다시 시작하세요."

    def stop(self) -> str:
        self.pending_task = None
        self.cache.clear()
        return "🛑 Hermes 오케스트라 작업을 중단하고 대기 상태로 전환했습니다."

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
        return await self._run_workflow("review", message, TASK_AGENTS["review"], "review")

    async def code(self, message: str) -> str:
        return await self.task(message)

    def models_text(self) -> str:
        lines = ["🧠 <b>Hermes 모델 상태</b>"]
        for provider in ALL_PROVIDERS:
            client = HermesAIClient.from_env(provider)
            mark = "✓" if client.config.enabled else "—"
            model = client.config.model or "not configured"
            lines.append(f"{mark} {provider}: {html.escape(model)}")
        return "\n".join(lines)

    def agents_text(self) -> str:
        lines = ["🔱 <b>HERMES 에이전트 팀</b>"]
        for name, spec in AGENT_TEAM.items():
            client = HermesAIClient.from_env(f"nvidia:{spec.model}")
            mark = "✓" if client.config.enabled else "—"
            lines.append(f"{mark} {spec.icon} {name}: {html.escape(spec.role)}")
            lines.append(f"   model={html.escape(spec.model)}")
        return "\n".join(lines)

    def status_text(self) -> str:
        lines = ["📊 <b>HERMES 상태</b>"]
        if self.pending_task:
            lines.append(f"진행/승인 대기: {html.escape(self.pending_task.message[:200])}")
            lines.append(f"소집: {', '.join(self.pending_task.agents)}")
        else:
            lines.append("진행 중인 승인 대기 태스크 없음")
        lines.extend(["", self.models_text(), "", "프로세스 사용량:"])
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
        self.pending_task = None

    async def _run_workflow(self, workflow: str, message: str, agents: tuple[str, ...], task_type: str) -> str:
        task_id = hashlib.md5(f"{time.time()}:{message}".encode("utf-8")).hexdigest()[:8]
        start = _format_task_start(message, agents)
        round_one = await self._collect_agent_round(message, agents, workflow, task_type)
        if not round_one:
            fallback = await self._ask_chain(("nvidia",), message, workflow)
            return start + "\n\n" + fallback
        synthesis = await self._synthesize(message, round_one, task_type)
        validation = await self._validate_with_ares(message, synthesis, round_one)
        verdict = str(validation.get("verdict") or validation.get("approval") or "CONDITIONAL").upper()
        consensus = str(synthesis.get("consensus") or synthesis.get("reply") or synthesis.get("recommendation") or "합의안 생성 실패")
        server_action = _server_action_required(message, consensus)
        self.pending_task = PendingTask(
            task_id=task_id,
            task_type=task_type,
            message=message,
            agents=agents,
            consensus=consensus,
            ares_verdict=verdict,
            server_action=server_action,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return _format_workflow_report(start, round_one, synthesis, validation, server_action)

    async def _collect_agent_round(
        self, message: str, agents: tuple[str, ...], workflow: str, task_type: str
    ) -> list[tuple[str, dict[str, Any]]]:
        results = await asyncio.gather(
            *(self._call_agent(agent, message, workflow, task_type) for agent in agents),
            return_exceptions=True,
        )
        collected: list[tuple[str, dict[str, Any]]] = []
        for agent, result in zip(agents, results):
            if isinstance(result, dict) and result:
                collected.append((agent, result))
        return collected

    async def _synthesize(self, message: str, opinions: list[tuple[str, dict[str, Any]]], task_type: str) -> dict[str, Any]:
        payload = {
            "task_type": task_type,
            "master_command": message[:4000],
            "agent_opinions": [
                {"agent": agent, "opinion": opinion} for agent, opinion in opinions
            ],
            "instruction": "중복을 제거하고 단일 실행안으로 합의안을 만든다.",
        }
        result = await self._call_agent("HERMES", payload, "synthesis", task_type)
        return result or {"consensus": "에이전트 의견을 종합했지만 HERMES 합성 응답이 비어 있습니다."}

    async def _validate_with_ares(
        self, message: str, synthesis: dict[str, Any], opinions: list[tuple[str, dict[str, Any]]]
    ) -> dict[str, Any]:
        payload = {
            "master_command": message[:4000],
            "consensus": synthesis,
            "agent_count": len(opinions),
            "instruction": "합의안을 검증한다. 치명적 문제가 있으면 verdict를 VETO로 둔다.",
        }
        result = await self._call_agent("ARES", payload, "final_validation", "review")
        return result or {"verdict": "CONDITIONAL", "summary": "ARES 검증 응답이 비어 있어 조건부로 둔다."}

    async def _call_agent(self, agent_name: str, message: str | dict[str, Any], workflow: str, task_type: str) -> dict[str, Any] | None:
        spec = AGENT_TEAM[agent_name]
        payload = {
            "agent": spec.name,
            "role": spec.role,
            "stance": spec.stance,
            "workflow": workflow,
            "task_type": task_type,
            "master_command": message if isinstance(message, str) else "",
            "context": message if isinstance(message, dict) else {},
            "output_contract": {
                "summary": "핵심 의견 1~3문장",
                "position": "찬성/반대/조건부 중 하나",
                "recommendation": "실행 가능한 단일 제안",
                "concerns": "주의할 점 배열",
                "verdict": "APPROVED/CONDITIONAL/VETO 중 하나",
            },
        }
        result = await self._complete_with_provider(f"nvidia:{spec.model}", payload)
        if result:
            result["_agent"] = agent_name
            result["_model_used"] = spec.model
        return result

    async def _call_agent_text(self, agent_name: str, message: str, mode: str) -> str:
        result = await self._call_agent(agent_name, message, mode, "chat")
        if not result:
            return await self._ask_chain(("nvidia",), message, mode)
        return _format_agent_text(agent_name, result)

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
        "You are one member of the HERMES AI Orchestrator team on Server A. "
        "Follow the assigned agent role and stance. Answer in Korean. Do not expose secrets. "
        "Do not claim that code, servers, deployments, or Server B were changed. "
        "Return strict JSON with keys: summary, position, recommendation, concerns, verdict, consensus, reply, suggested_commands."
    )


def _format_reply(provider: str, result: dict[str, Any], used: list[str] | None = None) -> str:
    reply = _clip(str(result.get("reply") or result.get("reason") or "응답이 비어 있습니다."), REPLY_MAX_CHARS)
    persona = str(result.get("persona") or provider)
    commands = result.get("suggested_commands") or []
    extra = ""
    if commands:
        extra += "\n\n제안 명령:\n" + "\n".join(f"- {cmd}" for cmd in commands[:5])
    source = "+".join(used) if used else str(result.get("_provider_used") or provider)
    return f"🤖 <b>{html.escape(persona)}</b> <i>{html.escape(source)}</i>\n{html.escape(reply + extra)}"


def _format_agent_text(agent_name: str, result: dict[str, Any]) -> str:
    spec = AGENT_TEAM[agent_name]
    reply = str(result.get("reply") or result.get("summary") or result.get("recommendation") or "응답이 비어 있습니다.")
    return f"{spec.icon} <b>{agent_name}</b>\n{html.escape(_clip(reply, 900))}"


def _format_task_start(message: str, agents: tuple[str, ...]) -> str:
    return (
        "🔱 <b>HERMES</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📋 태스크: {html.escape(message[:700])}\n"
        f"🤖 소집: {html.escape(', '.join(agents))}\n"
        "🔄 예상 단계: 의견 수집 → 합의안 → ARES 검증 → 승인 대기\n"
        "━━━━━━━━━━━━━━━"
    )


def _format_workflow_report(
    start: str,
    round_one: list[tuple[str, dict[str, Any]]],
    synthesis: dict[str, Any],
    validation: dict[str, Any],
    server_action: str,
) -> str:
    opinions = []
    for agent, result in round_one[:6]:
        spec = AGENT_TEAM[agent]
        summary = str(result.get("summary") or result.get("recommendation") or result.get("reply") or "의견 없음")
        opinions.append(f"{spec.icon} <b>{agent}</b>: {html.escape(_clip(summary, 140))}")
    consensus = str(
        synthesis.get("consensus") or synthesis.get("recommendation") or synthesis.get("reply") or "합의안 없음"
    )
    verdict = str(validation.get("verdict") or validation.get("approval") or "CONDITIONAL").upper()
    validation_summary = str(validation.get("summary") or validation.get("recommendation") or "")
    return (
        f"{start}\n\n"
        "💬 <b>토론 라운드 1</b>\n"
        "━━━━━━━━━━━━━━━\n"
        + "\n".join(opinions)
        + "\n━━━━━━━━━━━━━━━\n"
        f"🔱 <b>HERMES 중재</b>: {html.escape(_clip(consensus, 650))}\n\n"
        "✅ <b>합의 완료 — 승인 대기</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📌 합의안: {html.escape(_clip(consensus, 800))}\n"
        f"🛡 ARES 검증: {html.escape(verdict)}"
        + (f" — {html.escape(_clip(validation_summary, 180))}" if validation_summary else "")
        + f"\n🖥 서버 실행: {html.escape(server_action)}\n"
        "/approve — 실행 승인\n"
        "/reject 이유 — 재작업\n"
        "━━━━━━━━━━━━━━━"
    )


def _classify_task(message: str) -> str:
    lowered = message.lower()
    if any(word in lowered for word in ("버그", "오류", "안돼", "에러", "fix", "bug")):
        return "bug"
    if any(word in lowered for word in ("배포", "서버", "systemd", "docker", "deploy", "restart")):
        return "deploy"
    if any(word in lowered for word in ("리뷰", "review", "검토")):
        return "review"
    if any(word in lowered for word in ("성능", "최적화", "느려", "benchmark", "optimize")):
        return "performance"
    if any(word in lowered for word in ("조사", "찾아", "비교", "research", "라이브러리")):
        return "research"
    if any(word in lowered for word in ("구조", "설계", "아키텍처", "architecture")):
        return "architecture"
    if any(word in lowered for word in ("스크립트", "자동화", "cron", "automation")):
        return "automation"
    return "feature"


def _server_action_required(message: str, consensus: str) -> str:
    lowered = f"{message}\n{consensus}".lower()
    if any(word in lowered for word in ("server b", "프로덕션", "서비스 재시작", "systemctl restart", "db 변경", "database migration")):
        return "승인 필요"
    if any(word in lowered for word in ("테스트", "조회", "확인", "compile", "unittest", "읽기")):
        return "필요"
    return "불필요"


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


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 12)].rstrip() + " …"
