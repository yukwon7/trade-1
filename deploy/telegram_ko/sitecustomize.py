"""Korean output and local commands for Freqtrade's built-in Telegram RPC.

Command names stay unchanged so upstream handlers remain compatible.  Only text
sent to Telegram is translated.  Loaded automatically through PYTHONPATH.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from freqtrade.rpc.telegram import CommandHandler, Telegram, authorized_only

try:
    from trade_learning import latest_review_summary
except Exception:
    latest_review_summary = None


_REPLACEMENTS = (
    ("Dry run is enabled. All trades are simulated.", "모의투자가 활성화되어 있습니다. 모든 거래는 가상 체결입니다."),
    ("Simulated balances in Dry Mode.", "모의투자 잔고입니다."),
    ("No open trade found.", "열린 포지션이 없습니다."),
    ("No active locks.", "활성화된 거래 잠금이 없습니다."),
    ("No trades yet.", "아직 거래 내역이 없습니다."),
    ("No closed trade", "종료된 거래 없음"),
    ("New Trade filled", "신규 포지션 체결"),
    ("New Trade", "신규 포지션"),
    ("Increasing position", "포지션 추가 진입"),
    ("Position increase filled", "추가 진입 체결"),
    ("Partially exited", "부분 청산 완료"),
    ("Partially exiting", "부분 청산 중"),
    ("Exited", "청산 완료"),
    ("Exiting", "청산 중"),
    ("Cancelling enter Order", "진입 주문 취소"),
    ("Cancelling exit Order", "청산 주문 취소"),
    ("Searching for USDT pairs to buy and sell based on", "다음 페어 목록에서 매수·매도 신호를 탐색합니다:"),
    ("Bot Control", "봇 제어"),
    ("Current state", "현재 상태"),
    ("Statistics", "통계"),
    ("Starts the trader", "거래 봇 시작"),
    ("Stops the trader", "거래 봇 중지"),
    ("This help message", "이 도움말 표시"),
    ("Show version", "버전 표시"),
    ("Lists all open trades", "열린 포지션 전체 표시"),
    ("Lists cumulative profit from all finished trades", "종료된 모든 거래의 누적 수익 표시"),
    ("Show bot managed balance per currency", "봇이 관리하는 통화별 잔고 표시"),
    ("Show account balance per currency", "계정의 통화별 전체 잔고 표시"),
    ("Show number of active trades compared to allowed number of trades", "현재 포지션 수와 허용 포지션 수 표시"),
    ("Show running configuration", "실행 중인 설정 표시"),
    ("Show currently locked pairs", "현재 잠긴 페어 표시"),
    ("Show performance of each finished trade grouped by pair", "페어별 종료 거래 성과 표시"),
    ("Warning", "경고"),
    ("ERROR", "오류"),
    ("Status", "상태"),
    ("Exchange", "거래소"),
    ("Stake per trade", "포지션당 증거금"),
    ("Minimum ROI", "최소 목표수익률"),
    ("Trailing Stoploss", "추적 손절"),
    ("Stoploss distance", "손절가까지 거리"),
    ("Initial Stoploss", "초기 손절가"),
    ("Stoploss", "손절"),
    ("Position adjustment", "포지션 추가 진입"),
    ("Timeframe", "타임프레임"),
    ("Strategy", "전략"),
    ("Trade ID", "거래 ID"),
    ("Current Pair", "현재 페어"),
    ("Pair", "페어"),
    ("Enter Tag", "진입 태그"),
    ("Exit Reason", "청산 사유"),
    ("Direction", "방향"),
    ("Amount", "수량"),
    ("Total invested", "총 투자금"),
    ("Open Rate", "진입 가격"),
    ("Current Rate", "현재 가격"),
    ("Close Rate", "종료 가격"),
    ("Exit Rate", "청산 가격"),
    ("Open Date", "진입 시각"),
    ("Close Date", "종료 시각"),
    ("Unrealized Profit", "미실현 손익"),
    ("Realized Profit", "실현 손익"),
    ("Cumulative Profit", "누적 손익"),
    ("Final Profit", "최종 손익"),
    ("Total Profit", "총손익"),
    ("Close Profit", "종료 손익"),
    ("Profit factor", "수익 팩터"),
    ("Profit", "손익"),
    ("Liquidation", "청산가"),
    ("Duration", "보유 시간"),
    ("Remaining", "잔여 금액"),
    ("Starting capital", "시작 자본"),
    ("Available", "사용 가능"),
    ("Balance", "잔고"),
    ("Pending", "주문 중"),
    ("Bot Owned", "봇 소유"),
    ("Estimated Value", "추정 가치"),
    ("Total Trade Count", "총 거래 수"),
    ("Bot started", "봇 시작"),
    ("First Trade opened", "첫 거래 진입"),
    ("Latest Trade opened", "최근 거래 진입"),
    ("Win / Loss", "승 / 패"),
    ("Winrate", "승률"),
    ("Avg. Duration", "평균 보유 시간"),
    ("Best Performing", "최고 성과"),
    ("Trading volume", "거래량"),
    ("Max Drawdown", "최대 낙폭"),
    ("Current Drawdown", "현재 낙폭"),
    ("Long", "롱"),
    ("Short", "숏"),
    ("running", "실행 중"),
    ("stopped", "중지됨"),
    ("Stake amount updated", "포지션당 증거금 변경 완료"),
)

_CONFIG_PATH = Path(os.getenv("TRADE_CONFIG_PATH", "/freqtrade/user_data/config.json"))
_MIN_STAKE = float(os.getenv("TELEGRAM_STAKE_MIN", "1"))
_MAX_STAKE = float(os.getenv("TELEGRAM_STAKE_MAX", "100"))


def _translate_ko(message: str) -> str:
    for source, target in _REPLACEMENTS:
        message = message.replace(source, target)
    return message


_original_send_msg = Telegram._send_msg
_original_startup_telegram = Telegram._startup_telegram
_original_help = Telegram._help


async def _send_msg_ko(self, msg: str, *args, **kwargs):
    if isinstance(msg, str):
        msg = _translate_ko(msg)
    return await _original_send_msg(self, msg, *args, **kwargs)


def _format_stake(value: float | int | str) -> str:
    try:
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.4f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def _load_main_config() -> dict:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _save_main_config(config: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(_CONFIG_PATH.parent),
        prefix=f"{_CONFIG_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(config, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(_CONFIG_PATH)


@authorized_only
async def _stake_amount(self, update, context) -> None:
    """Handler for /stake.

    Usage:
    /stake       - show current stake_amount
    /stake 20    - set stake_amount to 20 USDT for new entries
    """

    try:
        config = _load_main_config()
    except Exception as exc:
        await self._send_msg(f"증거금 설정 파일을 읽지 못했습니다: `{exc}`")
        return

    current = config.get("stake_amount")
    stake_currency = config.get("stake_currency", "USDT")
    if not context.args:
        await self._send_msg(
            "포지션당 증거금 설정\n"
            f"현재: `{_format_stake(current)} {stake_currency}`\n"
            f"변경: `/stake 20` 처럼 입력하세요. 허용 범위: "
            f"`{_format_stake(_MIN_STAKE)}~{_format_stake(_MAX_STAKE)} {stake_currency}`\n"
            "주의: 이미 열린 포지션은 바뀌지 않고 다음 신규 진입부터 적용됩니다."
        )
        return

    raw_value = str(context.args[0]).strip().replace(",", "")
    try:
        new_stake = float(raw_value)
    except ValueError:
        await self._send_msg("숫자로 입력하세요. 예: `/stake 20`")
        return

    if not (_MIN_STAKE <= new_stake <= _MAX_STAKE):
        await self._send_msg(
            f"거부됨: 허용 범위는 `{_format_stake(_MIN_STAKE)}~"
            f"{_format_stake(_MAX_STAKE)} {stake_currency}` 입니다."
        )
        return

    if not config.get("dry_run", False):
        await self._send_msg("거부됨: 이 텔레그램 증거금 변경 명령은 dry-run에서만 허용됩니다.")
        return

    config["stake_amount"] = int(new_stake) if new_stake.is_integer() else new_stake
    try:
        _save_main_config(config)
        msg = self._rpc._rpc_reload_config()
    except Exception as exc:
        await self._send_msg(f"설정 변경 실패: `{exc}`")
        return

    notional = new_stake * 20
    await self._send_msg(
        "포지션당 증거금 변경 완료\n"
        f"이전: `{_format_stake(current)} {stake_currency}`\n"
        f"현재: `{_format_stake(new_stake)} {stake_currency}`\n"
        f"20배 기준 명목 포지션: 약 `{_format_stake(notional)} {stake_currency}`\n"
        f"반영 상태: `{msg.get('status', 'reloaded')}`\n"
        "적용 범위: 다음 신규 포지션부터"
    )


@authorized_only
async def _learn_review(self, update, context) -> None:
    command = ""
    if update and getattr(update, "effective_message", None):
        text = getattr(update.effective_message, "text", "") or ""
        command = text.split()[0].lstrip("/").split("@")[0]

    kind = "daily"
    if command in {"learn_weekly", "weekly_review"}:
        kind = "weekly"
    elif command in {"learn_monthly", "monthly_review"}:
        kind = "monthly"
    elif context.args and context.args[0] in {"daily", "weekly", "monthly"}:
        kind = context.args[0]

    if latest_review_summary is None:
        await self._send_msg("복기 DB 모듈을 불러오지 못했습니다.")
        return
    try:
        summary = latest_review_summary(kind)
    except Exception as exc:
        await self._send_msg(f"복기 리포트를 읽지 못했습니다: `{exc}`")
        return
    label = {"daily": "일일", "weekly": "주간", "monthly": "월간"}[kind]
    await self._send_msg(f"*{label} 학습 복기*\n```text\n{summary}\n```")


async def _startup_telegram_with_stake(self, *args, **kwargs):
    if not getattr(self, "_trade1_stake_handler_registered", False):
        self._app.add_handler(CommandHandler(["stake", "stake_amount"], self._stake_amount))
        self._app.add_handler(
            CommandHandler(
                ["learn", "learn_daily", "daily_review", "learn_weekly", "weekly_review", "learn_monthly", "monthly_review"],
                self._learn_review,
            )
        )
        self._trade1_stake_handler_registered = True
    return await _original_startup_telegram(self, *args, **kwargs)


@authorized_only
async def _help_with_stake(self, update, context) -> None:
    await _original_help(self, update, context)
    await self._send_msg(
        "_Trade-1 추가 명령_\n"
        "------------\n"
        "*/stake:* `현재 포지션당 증거금 표시`\n"
        "*/stake <USDT>:* `다음 신규 포지션부터 사용할 증거금 변경. 예: /stake 20`\n"
        "*/learn:* `최근 일일 복기 표시`\n"
        "*/learn_weekly:* `최근 주간 복기 표시`\n"
        "*/learn_monthly:* `최근 월간 복기 표시`"
    )


Telegram._send_msg = _send_msg_ko
Telegram._stake_amount = _stake_amount
Telegram._learn_review = _learn_review
Telegram._startup_telegram = _startup_telegram_with_stake
Telegram._help = _help_with_stake
