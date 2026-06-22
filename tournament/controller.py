from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from strategies import STRATEGIES


class TournamentController:
    """Combines local operator control with analysis-server lock results."""

    def __init__(self, config_dir: Path, default_mode: str = "MODE_B"):
        self.control_path = config_dir / "tournament_control.json"
        self.result_path = config_dir / "tournament_result.json"
        self.default_mode = default_mode
        self._control = self._load_control()
        self._result: dict = {}
        self._result_mtime = -1
        self._last_strategy = ""

    @property
    def mode(self) -> str:
        return self._control.get("mode", self.default_mode)

    @property
    def manual_strategy(self) -> str | None:
        value = self._control.get("manual_strategy")
        return value if value in STRATEGIES else None

    @property
    def locked_strategy(self) -> str | None:
        self._reload_result()
        value = self._result.get("locked_strategy")
        return value if value in STRATEGIES else None

    def active_strategy_id(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        if self.manual_strategy:
            return self.manual_strategy
        if self.locked_strategy:
            return self.locked_strategy
        started = datetime.fromisoformat(self._control["rotation_started_at"])
        elapsed = now - started
        slot = int(elapsed.total_seconds() // (86400 if self.mode == "MODE_A" else 3600))
        ids = tuple(STRATEGIES)
        return ids[max(0, slot) % len(ids)]

    def active_strategy(self, now: datetime | None = None):
        return STRATEGIES[self.active_strategy_id(now)]

    def set_manual_strategy(self, strategy_id: str | None) -> None:
        if strategy_id is not None:
            strategy_id = strategy_id.upper()
            if strategy_id not in STRATEGIES:
                raise ValueError("strategy must be S01 through S10")
        self._control["manual_strategy"] = strategy_id
        self._control["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_control()

    def set_mode(self, mode: str) -> None:
        normalized = mode.strip().upper().replace("A", "MODE_A") if mode.strip().upper() == "A" else mode.strip().upper()
        if normalized == "B":
            normalized = "MODE_B"
        if normalized not in {"MODE_A", "MODE_B"}:
            raise ValueError("mode must be MODE_A or MODE_B")
        self._control.update({
            "mode": normalized,
            "manual_strategy": None,
            "rotation_started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write_control()

    def status(self) -> dict:
        active = self.active_strategy_id()
        source = "MANUAL" if self.manual_strategy else "LOCKED" if self.locked_strategy else self.mode
        return {
            "active_strategy": active,
            "strategy_name": STRATEGIES[active].name,
            "source": source,
            "mode": self.mode,
            "manual_strategy": self.manual_strategy,
            "locked_strategy": self.locked_strategy,
        }

    def _load_control(self) -> dict:
        try:
            data = json.loads(self.control_path.read_text(encoding="utf-8")) if self.control_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        now = datetime.now(timezone.utc).isoformat()
        control = {
            "mode": data.get("mode") if data.get("mode") in {"MODE_A", "MODE_B"} else self.default_mode,
            "manual_strategy": data.get("manual_strategy") if data.get("manual_strategy") in STRATEGIES else None,
            "rotation_started_at": data.get("rotation_started_at", now),
            "updated_at": data.get("updated_at", now),
        }
        self.control_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.control_path, control)
        return control

    def _reload_result(self) -> None:
        mtime = self.result_path.stat().st_mtime_ns if self.result_path.exists() else 0
        if mtime == self._result_mtime:
            return
        self._result_mtime = mtime
        try:
            data = json.loads(self.result_path.read_text(encoding="utf-8")) if self.result_path.exists() else {}
            self._result = data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            self._result = {}

    def _write_control(self) -> None:
        self._atomic_write(self.control_path, self._control)

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
