"""Recover completed dry-run trades from Freqtrade journal JSON.

Usage on the server:
  journalctl -u trade-freqtrade -o json --no-pager | \
    docker exec -i --user 1000:1000 trade-freqtrade \
    python /freqtrade/user_data/strategies/recover_journal_trades.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from trade_learning import rebuild_signal_stats, record_event, upsert_trade_result


def _field(text: str, name: str) -> str | None:
    match = re.search(rf"'{re.escape(name)}':\s*'([^']*)'", text)
    return match.group(1) if match else None


def _number(text: str, name: str) -> float | None:
    match = re.search(rf"'{re.escape(name)}':\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)", text, re.I)
    return float(match.group(1)) if match else None


def _journal_datetime(text: str, name: str) -> str | None:
    match = re.search(rf"'{re.escape(name)}':\s*datetime\.datetime\(([^)]*)\)", text)
    if not match:
        return None
    numbers = [int(value) for value in re.findall(r"\d+", match.group(1))[:7]]
    if len(numbers) < 6:
        return None
    numbers += [0] * (7 - len(numbers))
    return datetime(*numbers[:7], tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _recovered_id(pair: str, open_date: str) -> int:
    digest = hashlib.sha1(f"{pair}|{open_date}".encode()).hexdigest()
    return -(int(digest[:12], 16) % 2_000_000_000 + 1)


def parse_exit_messages(lines: list[str]) -> list[dict[str, Any]]:
    messages: list[str] = []
    buffer = ""
    for line in lines:
        try:
            message = str(json.loads(line).get("MESSAGE", ""))
        except (json.JSONDecodeError, AttributeError):
            continue
        if "Sending rpc message: {" in message and "'type': exit_fill" in message:
            buffer = message.split("Sending rpc message: ", 1)[1]
        elif buffer:
            buffer += " " + message
        if buffer and buffer.rstrip().endswith("}"):
            messages.append(buffer)
            buffer = ""

    recovered: list[dict[str, Any]] = []
    seen: set[int] = set()
    for message in messages:
        if _field(message, "is_final_exit") == "False" or "'is_final_exit': False" in message:
            continue
        pair = _field(message, "pair")
        open_date = _journal_datetime(message, "open_date")
        close_date = _journal_datetime(message, "close_date")
        if not pair or not open_date or not close_date:
            continue
        trade_id = _recovered_id(pair, open_date)
        if trade_id in seen:
            continue
        seen.add(trade_id)
        direction = (_field(message, "direction") or "Long").lower()
        profit_ratio = _number(message, "final_profit_ratio")
        if profit_ratio is None:
            profit_ratio = _number(message, "profit_ratio")
        recovered.append(
            {
                "trade_id": trade_id,
                "pair": pair,
                "is_short": direction == "short",
                "is_open": False,
                "strategy": "recovered_from_journal",
                "enter_tag": _field(message, "enter_tag"),
                "open_date": open_date,
                "close_date": close_date,
                "open_rate": _number(message, "open_rate"),
                "close_rate": _number(message, "close_rate"),
                "stake_amount": _number(message, "stake_amount"),
                "leverage": _number(message, "leverage"),
                "profit_ratio": profit_ratio,
                "profit_pct": profit_ratio * 100 if profit_ratio is not None else None,
                "profit_abs": _number(message, "profit_amount"),
                "exit_reason": _field(message, "exit_reason"),
            }
        )
    return recovered


def main() -> int:
    trades = parse_exit_messages(sys.stdin.readlines())
    imported = sum(1 for trade in trades if upsert_trade_result(trade))
    rebuild_signal_stats()
    record_event("journal_recovery", f"recovered {imported} completed trades", {"count": imported})
    print(f"journal recovery complete: {imported} completed trades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
