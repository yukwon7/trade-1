from __future__ import annotations

from datetime import datetime, timedelta, timezone


class CircuitBreaker:
    def __init__(self, store):
        self.store = store

    async def allow_entry(self, symbol: str, balance: float) -> tuple[bool, str, str]:
        stats = await self.store.risk_state(symbol)
        now = datetime.now(timezone.utc)
        if balance > 0 and stats["daily_pnl"] <= -(balance * 0.03):
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return False, "DAILY_LOSS_LIMIT", tomorrow.isoformat()
        if stats["consecutive_losses"] >= 3 and stats["last_loss_at"]:
            if now - datetime.fromisoformat(stats["last_loss_at"]) < timedelta(hours=1):
                return False, "THREE_LOSSES_PAUSE", (datetime.fromisoformat(stats["last_loss_at"]) + timedelta(hours=1)).isoformat()
        if stats["symbol_last_stop_at"]:
            if now - datetime.fromisoformat(stats["symbol_last_stop_at"]) < timedelta(minutes=30):
                return False, "SYMBOL_STOP_COOLDOWN", (datetime.fromisoformat(stats["symbol_last_stop_at"]) + timedelta(minutes=30)).isoformat()
        if stats["symbol_last_10_count"] >= 10 and stats["symbol_last_10_losses"] >= 7 and stats["symbol_last_loss_at"]:
            if now - datetime.fromisoformat(stats["symbol_last_loss_at"]) < timedelta(hours=6):
                return False, "SYMBOL_SIX_HOUR_BLOCK", (datetime.fromisoformat(stats["symbol_last_loss_at"]) + timedelta(hours=6)).isoformat()
        return True, "OK", ""
