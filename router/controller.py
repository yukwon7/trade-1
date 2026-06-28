from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from strategies import STRATEGIES, STRATEGY_ROTATION_IDS


class RouterController:
    """Operator control for the chart-adaptive router."""

    def __init__(self, config_dir: Path):
        self.control_path = config_dir / "router_control.json"
        self._control = self._load_control()

    @property
    def manual_strategy(self) -> str | None:
        value = self._control.get("manual_strategy")
        return value if value in STRATEGIES else None

    def active_strategy_id(self, now: datetime | None = None) -> str:
        if self.manual_strategy:
            return self.manual_strategy
        return STRATEGY_ROTATION_IDS[0]

    def active_strategy(self, now: datetime | None = None):
        return STRATEGIES[self.active_strategy_id(now)]

    def set_manual_strategy(self, strategy_id: str | None) -> None:
        if strategy_id is not None:
            strategy_id = strategy_id.upper()
            if strategy_id not in STRATEGIES:
                raise ValueError("unknown strategy id")
        self._control["manual_strategy"] = strategy_id
        self._control["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_control()

    def status(self) -> dict:
        active = self.active_strategy_id()
        source = "MANUAL" if self.manual_strategy else "ROUTER"
        return {
            "active_strategy": active,
            "strategy_name": STRATEGIES[active].name,
            "source": source,
            "manual_strategy": self.manual_strategy,
        }

    def _load_control(self) -> dict:
        try:
            data = json.loads(self.control_path.read_text(encoding="utf-8")) if self.control_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        now = datetime.now(timezone.utc).isoformat()
        control = {
            "manual_strategy": data.get("manual_strategy") if data.get("manual_strategy") in STRATEGIES else None,
            "updated_at": data.get("updated_at", now),
        }
        self.control_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.control_path, control)
        return control

    def _write_control(self) -> None:
        self._atomic_write(self.control_path, self._control)

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
