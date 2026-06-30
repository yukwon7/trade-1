from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CodexBridge:
    config_dir: Path
    project_dir: Path

    @property
    def queue_path(self) -> Path:
        return self.config_dir / "codex_tasks.json"

    def enqueue(self, prompt: str, source: str = "telegram", report: str = "") -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt is empty")
        tasks = self._read()
        task = {
            "id": uuid.uuid4().hex[:10],
            "status": "queued",
            "source": source,
            "prompt": prompt[:8000],
            "report": report[:3000],
            "created_at": _now(),
            "updated_at": _now(),
            "result": "",
            "error": "",
        }
        tasks.append(task)
        self._write(tasks)
        return task

    def status_text(self, task_id: str = "") -> str:
        tasks = self._read()
        if task_id:
            tasks = [task for task in tasks if task["id"] == task_id]
        if not tasks:
            return "Codex 작업이 없습니다.\n" + self.diagnostic_text()
        lines = ["🧩 <b>Codex 작업 큐</b>"]
        for task in tasks[-8:]:
            lines.append(
                f"- {task['id']} | {task['status']} | {task['source']} | {task['prompt'][:80]}"
            )
        lines.append(self.diagnostic_text())
        return "\n".join(lines)

    def codex_available(self) -> bool:
        command = os.getenv("CODEX_CLI_COMMAND", "codex").split()[0]
        return bool(shutil.which(command))

    def direct_run_enabled(self) -> bool:
        return os.getenv("HERMES_CODEX_DIRECT_RUN", "false").lower() == "true"

    def auth_status(self) -> str:
        command = os.getenv("CODEX_CLI_COMMAND", "codex").split()[0]
        if not shutil.which(command):
            return "cli_missing"
        try:
            completed = subprocess.run(
                [command, "doctor"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception:
            return "unknown"
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        if "no codex credentials" in output or "codex login" in output or "provide an api key" in output:
            return "auth_missing"
        if completed.returncode == 0:
            return "ready"
        return "unknown"

    def diagnostic_text(self) -> str:
        cli = "있음" if self.codex_available() else "없음"
        direct = "켜짐" if self.direct_run_enabled() else "꺼짐"
        auth_map = {
            "ready": "인증됨",
            "auth_missing": "인증 필요",
            "cli_missing": "CLI 없음",
            "unknown": "확인 불가",
        }
        auth = auth_map.get(self.auth_status(), "확인 불가")
        return f"Codex CLI: {cli} | 직접 실행: {direct} | 인증: {auth}"

    def run_once(self) -> dict[str, Any]:
        tasks = self._read()
        for task in tasks:
            if task.get("status") == "queued":
                return self._run_task(task, tasks)
        return {"status": "idle", "message": "queued task not found"}

    def _run_task(self, task: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.direct_run_enabled():
            task["status"] = "blocked"
            task["error"] = "HERMES_CODEX_DIRECT_RUN is not true"
            task["updated_at"] = _now()
            self._write(tasks)
            return task
        if not self.codex_available():
            task["status"] = "blocked"
            task["error"] = "codex CLI not found on this server"
            task["updated_at"] = _now()
            self._write(tasks)
            return task
        auth = self.auth_status()
        if auth != "ready":
            task["status"] = "blocked"
            task["error"] = "Codex CLI authentication is required on Server A"
            task["updated_at"] = _now()
            self._write(tasks)
            return task
        task["status"] = "running"
        task["updated_at"] = _now()
        self._write(tasks)
        output_path = self.config_dir / f"codex_task_{task['id']}_last_message.txt"
        prompt = _build_codex_prompt(task)
        command = [
            *os.getenv("CODEX_CLI_COMMAND", "codex").split(),
            "exec",
            "--cd",
            str(self.project_dir),
            "--sandbox",
            os.getenv("CODEX_SANDBOX", "workspace-write"),
            "-c",
            'approval_policy="never"',
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            "-",
        ]
        timeout = int(os.getenv("CODEX_WORKER_TIMEOUT_SECONDS", "1800"))
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                cwd=self.project_dir,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            task["status"] = "done" if completed.returncode == 0 else "failed"
            task["result"] = output_path.read_text(encoding="utf-8", errors="replace")[:4000] if output_path.exists() else completed.stdout[-4000:]
            task["error"] = completed.stderr[-2000:]
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
        task["updated_at"] = _now()
        self._write(tasks)
        return task

    def _read(self) -> list[dict[str, Any]]:
        if not self.queue_path.exists():
            return []
        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _write(self, tasks: list[dict[str, Any]]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.queue_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.queue_path)


def _build_codex_prompt(task: dict[str, Any]) -> str:
    return (
        "You are Codex working from a Telegram-created Hermes task.\n"
        "Keep changes safe, preserve secrets, run relevant tests, and summarize changed files.\n"
        "Do not touch Server B unless the task explicitly requires config-only deployment.\n\n"
        f"Task ID: {task['id']}\n"
        f"Source: {task['source']}\n"
        f"Prompt:\n{task['prompt']}\n\n"
        f"Hermes report:\n{task.get('report', '')}\n"
    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "run-once"])
    parser.add_argument("--config-dir", default=os.getenv("CONFIG_DIR", "config"))
    parser.add_argument("--project-dir", default=os.getenv("PROJECT_DIR", "."))
    args = parser.parse_args()
    bridge = CodexBridge(Path(args.config_dir), Path(args.project_dir))
    if args.command == "status":
        print(bridge.status_text())
        return 0
    print(json.dumps(bridge.run_once(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
