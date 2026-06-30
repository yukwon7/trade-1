from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SafeExecutor:
    project_dir: Path

    async def run(self, command: str, argument: str = "") -> str:
        command = command.lower().strip()
        if command == "server_status":
            return await self._exec(["bash", "-lc", "uptime; free -m | sed -n '1,2p'; df -h / | tail -1"])
        if command == "git_status":
            return await self._exec(["git", "status", "-sb"])
        if command == "run_tests":
            return await self._exec([str(self.project_dir / ".venv/bin/python"), "-m", "unittest", "discover", "-s", "tests"])
        if command == "logs":
            service = argument.strip() or "hermes-analysis-bot.service"
            if service not in {"hermes-analysis-bot.service", "hermes-analysis.service"}:
                return "허용되지 않은 로그 대상입니다."
            return await self._exec(["journalctl", "-u", service, "-n", "80", "--no-pager"])
        if command == "exec_status":
            return self.exec_status()
        return "지원하지 않는 실행 명령입니다."

    def exec_status(self) -> str:
        codex = shutil.which("codex")
        node = shutil.which("node")
        npm = shutil.which("npm")
        codex_auth = _codex_auth_status(self.project_dir) if codex else "CLI 없음"
        return (
            "🖥 <b>실행 상태</b>\n"
            f"- node: {'있음' if node else '없음'}\n"
            f"- npm: {'있음' if npm else '없음'}\n"
            f"- codex: {'있음' if codex else '없음'} ({codex_auth})\n"
            "- 안전 실행: server_status, git_status, run_tests, logs\n"
            "- Codex 직접 실행: /codex 작업등록 후 /codex_run"
        )

    async def _exec(self, args: list[str], timeout: int = 120) -> str:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return "명령 시간이 초과되었습니다."
        text = output.decode("utf-8", errors="replace")[-3500:]
        return f"<pre>{_escape(text)}</pre>"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _codex_auth_status(project_dir: Path) -> str:
    try:
        completed = subprocess.run(
            ["codex", "doctor"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return "인증 확인 불가"
    output = f"{completed.stdout}\n{completed.stderr}".lower()
    if "no codex credentials" in output or "codex login" in output or "provide an api key" in output:
        return "인증 필요"
    if completed.returncode == 0:
        return "인증됨"
    return "인증 확인 불가"
