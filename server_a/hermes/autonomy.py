from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess


async def post_autonomous_improvement(notifier, file_changed: str, reason: str) -> None:
    if notifier is None:
        return
    await notifier.send(f"🛠 자율 개선: {file_changed} — {reason}")


def append_changelog(file_changed: str, reason: str, what_changed: str, path: str | Path = "CHANGELOG.md") -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"- [AUTONOMOUS] {timestamp} | {file_changed} | {reason} | {what_changed}\n"
    changelog = Path(path)
    if not changelog.exists():
        changelog.write_text("# CHANGELOG\n\n", encoding="utf-8")
    with changelog.open("a", encoding="utf-8") as handle:
        handle.write(line)


async def commit_change(description: str) -> bool:
    """Auto-commit after an autonomous modification.

    Push is attempted only when GITHUB_REMOTE is set.  Secrets are still
    protected by .gitignore; this function does not print environment values.
    """
    if not Path(".git").exists():
        subprocess.run(["git", "init"], check=False)
    subprocess.run(["git", "add", "-A"], check=False)
    status = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
    if status.returncode == 0:
        return False
    subprocess.run(["git", "commit", "-m", f"[autonomous] {description}"], check=False)
    if os.getenv("GITHUB_REMOTE"):
        subprocess.run(["git", "push"], check=False)
    await asyncio.sleep(0)
    return True
