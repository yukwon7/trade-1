#!/usr/bin/env python3
"""Publish the curated Korean command menu to Telegram without exposing the token."""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


CONFIG_PATH = Path("/etc/trade-1/telegram.json")
COMMANDS = [
    ("daily", "오늘 손익과 열린 포지션"),
    ("status", "열린 포지션 상세"),
    ("profit", "전체 누적 손익"),
    ("balance", "모의투자 잔고"),
    ("stake", "포지션당 증거금 설정"),
    ("learn", "최근 일일 학습 복기"),
    ("learn_weekly", "최근 주간 학습 복기"),
    ("learn_monthly", "최근 월간 학습 복기"),
    ("trades", "최근 거래 내역"),
    ("performance", "코인별 거래 성과"),
    ("count", "현재 포지션 슬롯"),
    ("start", "거래 봇 시작"),
    ("pause", "신규 진입 일시정지"),
    ("stop", "거래 봇 중지"),
    ("help", "전체 명령 센터"),
]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_PATH
    telegram = json.loads(path.read_text(encoding="utf-8")).get("telegram", {})
    if not telegram.get("enabled"):
        print("Telegram is disabled; command menu unchanged.")
        return 0
    token = telegram["token"]
    payload = urllib.parse.urlencode(
        {
            "commands": json.dumps(
                [{"command": command, "description": description} for command, description in COMMANDS],
                ensure_ascii=False,
            )
        }
    ).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setMyCommands",
        data=payload,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the command menu update")
    print(f"Telegram command menu updated: {len(COMMANDS)} commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
