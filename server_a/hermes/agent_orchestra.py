from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

from server_a.hermes.clients.ai_client import HermesAIClient


AGENT_PERSONAS = {
    "hermes": "trading-system strategist. Focus on decisions, risk, and config safety.",
    "dev": "senior Python deployment engineer. Focus on safe repo changes and tests.",
    "risk": "risk manager. Block unsafe leverage, secret exposure, and direct live changes.",
    "qa": "test engineer. Ask for reproducible checks and rollback paths.",
}

SAFE_COMMANDS = {
    "git_status": ["git", "status", "-sb"],
    "git_diff_stat": ["git", "diff", "--stat"],
    "tests": ["/opt/trade-1/.venv/bin/python", "-m", "unittest", "discover", "-s", "tests", "-q"],
}


class AgentOrchestra:
    def __init__(self, project_dir: str | Path, max_history: int | None = None):
        self.project_dir = Path(project_dir)
        self.max_history = max_history or int(os.getenv("MAX_HISTORY_TURNS", "5"))
        self.history: deque[dict[str, str]] = deque(maxlen=max(1, self.max_history))

    async def chat(self, message: str, mode: str = "chat") -> str:
        client = HermesAIClient.from_env()
        if not client.config.enabled:
            return "AI provider가 설정되지 않았습니다. Server A .env의 HERMES_AI_PROVIDER/API_KEY를 확인하세요."
        payload = {
            "mode": mode,
            "message": message[:3000],
            "personas": AGENT_PERSONAS,
            "history": list(self.history),
            "constraints": [
                "Korean response",
                "Do not reveal or request secrets",
                "Server B execution changes require explicit config-only deployment",
                "For development, propose patch/test plan unless safe command is explicitly requested",
                "Return JSON only: reply, persona, suggested_commands, risk_notes",
            ],
        }
        result = await client.complete_json(_agent_system_prompt(), payload)
        if not result:
            return "AI 응답을 받지 못했습니다. 로그와 provider 상태를 확인하세요."
        reply = str(result.get("reply") or result.get("reason") or "응답이 비어 있습니다.")[:3500]
        persona = str(result.get("persona") or "hermes")
        notes = result.get("risk_notes") or []
        commands = result.get("suggested_commands") or []
        self.history.append({"user": message[:1000], "assistant": reply[:1000]})
        extra = ""
        if commands:
            extra += "\n\n제안 명령:\n" + "\n".join(f"- {cmd}" for cmd in commands[:5])
        if notes:
            extra += "\n\n리스크:\n" + "\n".join(f"- {note}" for note in notes[:5])
        return f"🤖 <b>{persona}</b>\n{_escape(reply + extra)}"

    def clear(self) -> None:
        self.history.clear()

    async def run_safe_command(self, name: str) -> str:
        command = SAFE_COMMANDS.get(name)
        if not command:
            return "지원하지 않는 safe command입니다."
        if name.startswith("git") and not (self.project_dir / ".git").exists():
            return "Server A 배포 디렉터리는 git checkout이 아닙니다. 소스 변경/커밋은 로컬 repo와 GitHub main에서 관리됩니다."
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=90)
        except asyncio.TimeoutError:
            process.kill()
            return f"{name} timeout"
        text = output.decode("utf-8", errors="replace")[-3500:]
        return f"<pre>{_escape(text)}</pre>\n완료: {name} ({time.monotonic() - started:.1f}s)"


def _agent_system_prompt() -> str:
    return (
        "You are Hermes Agent Orchestra on Server A. Use personas hermes/dev/risk/qa. "
        "Help with trading-system analysis and safe development. Never expose secrets. "
        "Never claim to modify Server B directly. Return strict JSON."
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
