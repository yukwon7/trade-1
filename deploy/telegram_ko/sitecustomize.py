"""Korean output and local commands for Freqtrade's built-in Telegram RPC.

Command names stay unchanged so upstream handlers remain compatible.  Only text
sent to Telegram is translated.  Loaded automatically through PYTHONPATH.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from freqtrade.rpc.telegram import CommandHandler, Telegram, authorized_only
from telegram.ext import MessageHandler, filters

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
    ("Using Protections", "보호 설정"),
    ("Cooldown period for", "재진입 대기"),
    ("open trades active", "개의 열린 포지션이 있습니다"),
    ("process died", "프로세스 종료"),
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
_LEARNING_DB_PATH = Path(
    os.getenv("TRADE_LEARNING_DB", "/freqtrade/user_data/learning/trade_learning.sqlite")
)
_MIN_STAKE = float(os.getenv("TELEGRAM_STAKE_MIN", "1"))
_MAX_STAKE = float(os.getenv("TELEGRAM_STAKE_MAX", "100"))
_DISPLAY_LEVERAGE = float(os.getenv("TELEGRAM_LEVERAGE", "5"))
_KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


def _translate_ko(message: str) -> str:
    for source, target in _REPLACEMENTS:
        message = message.replace(source, target)
    return message


_UI_PREFIXES = (
    "📊", "💵", "🧠", "🧭", "🧪", "🟢", "🔴", "🟡", "⚠️", "✅", "🚀", "🔎", "🛡️", "🤖", "ℹ️",
)
_DIVIDER = "━━━━━━━━━━━━"


def _polish_message(message: str) -> str:
    """Apply a consistent compact visual hierarchy to upstream Telegram text."""

    message = _translate_ko(message).strip()
    while "\n\n\n" in message:
        message = message.replace("\n\n\n", "\n\n")
    message = message.replace("------------", _DIVIDER)
    if not message or message.startswith(_UI_PREFIXES):
        return message

    title = None
    if "모의투자가 활성화" in message:
        title = "🧪 *모의투자 모드*"
    elif message.startswith("*거래소:*"):
        title = "🚀 *트레이딩 봇 시작*"
    elif message.startswith("다음 페어 목록"):
        title = "🔎 *시장 스캔 준비*"
    elif message.startswith("보호 설정"):
        title = "🛡️ *리스크 보호 설정*"
    elif "프로세스 종료" in message:
        title = "⚠️ *봇 상태 변경*"
    elif message.startswith("*신규 포지션"):
        message = "🟢 " + message
    elif message.startswith(("*청산 완료", "*부분 청산 완료")):
        message = "✅ " + message
    elif message.startswith(("*청산 중", "*부분 청산 중")):
        message = "🟡 " + message
    elif message.startswith("*경고"):
        message = "⚠️ " + message
    elif message.startswith("*오류"):
        message = "🔴 " + message

    if title:
        message = f"{title}\n{_DIVIDER}\n{message}"
    elif message.startswith(_UI_PREFIXES) and "\n" in message:
        first, rest = message.split("\n", 1)
        if not rest.startswith(_DIVIDER):
            message = f"{first}\n{_DIVIDER}\n{rest}"
    elif message.startswith("*") and "\n" in message:
        first, rest = message.split("\n", 1)
        if not rest.startswith(_DIVIDER):
            message = f"{first}\n{_DIVIDER}\n{rest}"
    return message


_original_send_msg = Telegram._send_msg
_original_startup_telegram = Telegram._startup_telegram
_original_help = Telegram._help


async def _send_msg_ko(self, msg: str, *args, **kwargs):
    if isinstance(msg, str):
        msg = _polish_message(msg)
    return await _original_send_msg(self, msg, *args, **kwargs)


def _format_stake(value: float | int | str) -> str:
    try:
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.4f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def _money(value: float | int | None, currency: str = "USDT") -> str:
    numeric = float(value or 0)
    return f"{numeric:+,.4f} {currency}"


def _result_icon(value: float | int | None) -> str:
    numeric = float(value or 0)
    return "🟢" if numeric > 0 else "🔴" if numeric < 0 else "⚪"


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
        await self._send_msg(f"🔴 *설정 읽기 실패*\n{_DIVIDER}\n`{exc}`")
        return

    current = config.get("stake_amount")
    stake_currency = config.get("stake_currency", "USDT")
    if not context.args:
        notional = float(current or 0) * _DISPLAY_LEVERAGE
        await self._send_msg(
            "💵 *포지션 금액 설정*\n"
            f"{_DIVIDER}\n"
            f"현재 증거금  `{_format_stake(current)} {stake_currency}`\n"
            f"{_format_stake(_DISPLAY_LEVERAGE)}배 포지션  `약 {_format_stake(notional)} {stake_currency}`\n"
            f"허용 범위    `{_format_stake(_MIN_STAKE)} ~ {_format_stake(_MAX_STAKE)} {stake_currency}`\n\n"
            "*변경 방법*\n"
            "`/stake 20`\n\n"
            "_열린 포지션은 유지되고 다음 진입부터 적용됩니다._"
        )
        return

    raw_value = str(context.args[0]).strip().replace(",", "")
    try:
        new_stake = float(raw_value)
    except ValueError:
        await self._send_msg("🟡 *입력값 확인*\n" + _DIVIDER + "\n숫자로 입력해 주세요.\n예시  `/stake 20`")
        return

    if not (_MIN_STAKE <= new_stake <= _MAX_STAKE):
        await self._send_msg(
            "🟡 *설정 범위 초과*\n"
            f"{_DIVIDER}\n"
            f"허용 범위  `{_format_stake(_MIN_STAKE)} ~ "
            f"{_format_stake(_MAX_STAKE)} {stake_currency}`"
        )
        return

    if not config.get("dry_run", False):
        await self._send_msg("🔴 *변경 차단*\n" + _DIVIDER + "\n이 명령은 모의투자 모드에서만 사용할 수 있습니다.")
        return

    config["stake_amount"] = int(new_stake) if new_stake.is_integer() else new_stake
    try:
        _save_main_config(config)
        msg = self._rpc._rpc_reload_config()
    except Exception as exc:
        await self._send_msg(f"🔴 *설정 변경 실패*\n{_DIVIDER}\n`{exc}`")
        return

    notional = new_stake * _DISPLAY_LEVERAGE
    await self._send_msg(
        "✅ *포지션 금액 변경 완료*\n"
        f"{_DIVIDER}\n"
        f"이전  `{_format_stake(current)} {stake_currency}`\n"
        f"현재  `{_format_stake(new_stake)} {stake_currency}`\n"
        f"{_format_stake(_DISPLAY_LEVERAGE)}배 포지션  `약 {_format_stake(notional)} {stake_currency}`\n\n"
        f"상태  `{msg.get('status', 'reloaded')}`\n"
        "_다음 신규 포지션부터 적용됩니다._"
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
        await self._send_msg("🔴 학습 리포트를 불러올 수 없습니다.", parse_mode=None)
        return
    try:
        summary = latest_review_summary(kind)
    except Exception as exc:
        await self._send_msg(f"🔴 학습 리포트 조회 실패\n{_DIVIDER}\n{exc}", parse_mode=None)
        return
    label = {"daily": "일일", "weekly": "주간", "monthly": "월간"}[kind]
    body_lines = summary.splitlines()
    if body_lines and "복기" in body_lines[0]:
        body_lines = body_lines[1:]
    body = "\n".join(line.replace("- ", "• ", 1) for line in body_lines)
    await self._send_msg(
        f"🧠 {label} 학습 리포트\n{_DIVIDER}\n{body}\n\n자동 복기 데이터 기반",
        parse_mode=None,
    )


def _parse_db_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _kst_time(value: str | None) -> str:
    parsed = _parse_db_time(value)
    return parsed.astimezone(_KST).strftime("%m-%d %H:%M") if parsed else "-"


def _daily_trade_report() -> str:
    """Return today's KST trade activity, including still-open positions."""

    now_kst = datetime.now(_KST)
    start_utc = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    start_text = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    if not _LEARNING_DB_PATH.exists():
        return "거래 기록 DB가 아직 생성되지 않았습니다."

    with sqlite3.connect(_LEARNING_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT trade_id, pair, side, is_open, open_date, close_date,
                   profit_abs, profit_ratio, leverage, enter_tag
            FROM trade_results
            WHERE open_date >= ? OR close_date >= ? OR is_open = 1
            ORDER BY COALESCE(close_date, open_date) DESC
            """,
            (start_text, start_text),
        ).fetchall()
        all_count = conn.execute("SELECT COUNT(*) FROM trade_results").fetchone()[0]

    opened_today = [row for row in rows if (_parse_db_time(row["open_date"]) or datetime.min.replace(tzinfo=timezone.utc)) >= start_utc]
    closed_today = [row for row in rows if not row["is_open"] and (_parse_db_time(row["close_date"]) or datetime.min.replace(tzinfo=timezone.utc)) >= start_utc]
    open_rows = [row for row in rows if row["is_open"]]
    realized = sum(float(row["profit_abs"] or 0) for row in closed_today)
    unrealized = sum(float(row["profit_abs"] or 0) for row in open_rows)
    wins = sum(1 for row in closed_today if float(row["profit_abs"] or 0) > 0)
    losses = sum(1 for row in closed_today if float(row["profit_abs"] or 0) < 0)
    winrate = (wins / len(closed_today) * 100) if closed_today else 0

    lines = [
        "📊 *오늘의 트레이딩*",
        f"`{now_kst:%Y.%m.%d} · KST`",
        _DIVIDER,
        "*PERFORMANCE*",
        f"실현 손익  `{_money(realized)}`",
        f"미실현    `{_money(unrealized)}`",
        f"승률       `{winrate:.1f}%`  ·  {wins}승 {losses}패",
        "",
        "*ACTIVITY*",
        f"진입  `{len(opened_today)}건`   청산  `{len(closed_today)}건`   진행  `{len(open_rows)}건`",
    ]
    if open_rows:
        lines.extend(["", "*OPEN POSITIONS*"])
    for row in open_rows[:5]:
        pair = str(row["pair"]).split("/")[0]
        side = "롱" if row["side"] == "long" else "숏"
        profit = float(row["profit_abs"] or 0)
        lines.append(
            f"{_result_icon(profit)} *{pair}*  {side} · {float(row['leverage'] or 1):g}x\n"
            f"    `{_money(profit)}`  ·  {_kst_time(row['open_date'])} 진입"
        )
    if closed_today:
        lines.extend(["", "*RECENT CLOSES*"])
    for row in closed_today[:6]:
        pair = str(row["pair"]).split("/")[0]
        side = "롱" if row["side"] == "long" else "숏"
        profit = float(row["profit_abs"] or 0)
        lines.append(
            f"{_result_icon(profit)} *{pair}*  {side}  `{_money(profit)}`  ·  {_kst_time(row['close_date'])}"
        )
    if not opened_today and not closed_today and not open_rows:
        lines.extend(["", "_오늘 저장된 진입·청산 기록이 없습니다._"])
    lines.extend(["", f"_누적 저장 {all_count}건 · 1분마다 자동 갱신_"])
    return "\n".join(lines)


@authorized_only
async def _daily_status(self, update, context) -> None:
    try:
        report = _daily_trade_report()
    except Exception as exc:
        await self._send_msg(f"🔴 *데일리 조회 실패*\n{_DIVIDER}\n`{exc}`")
        return
    logger.info("trade-1 daily report requested")
    await self._send_msg(report)


def _remove_upstream_daily_handler(app) -> int:
    """Remove Freqtrade's closed-trades-only /daily handler before polling starts."""

    removed = 0
    for group, handlers in list(app.handlers.items()):
        for handler in list(handlers):
            commands = getattr(handler, "commands", set())
            if "daily" in commands:
                app.remove_handler(handler, group=group)
                removed += 1
    return removed


async def _startup_telegram_with_stake(self, *args, **kwargs):
    if not getattr(self, "_trade1_stake_handler_registered", False):
        removed = _remove_upstream_daily_handler(self._app)
        self._app.add_handler(CommandHandler(["stake", "stake_amount"], self._stake_amount))
        self._app.add_handler(CommandHandler(["daily"], self._daily_status))
        self._app.add_handler(
            MessageHandler(filters.Regex(r"^\s*daily\s*$"), self._daily_status)
        )
        self._app.add_handler(
            CommandHandler(
                ["learn", "learn_daily", "daily_review", "learn_weekly", "weekly_review", "learn_monthly", "monthly_review"],
                self._learn_review,
            )
        )
        self._app.add_handler(CommandHandler(["menu"], self._help))
        self._app.add_handler(MessageHandler(filters.Regex(r"^\s*menu\s*$"), self._help))
        self._trade1_stake_handler_registered = True
        logger.info("trade-1 custom daily handler registered; removed_upstream=%d", removed)
    return await _original_startup_telegram(self, *args, **kwargs)


@authorized_only
async def _help_with_stake(self, update, context) -> None:
    await self._send_msg(_command_center_text())


def _command_center_text() -> str:
    return (
        "🧭 *TRADE·1 COMMAND CENTER*\n"
        f"{_DIVIDER}\n"
        "*OVERVIEW*\n"
        "`/daily`  오늘 손익과 포지션\n"
        "`/status`  열린 포지션 상세\n"
        "`/profit`  전체 누적 손익\n"
        "`/balance`  모의투자 잔고\n\n"
        "*CONTROL*\n"
        "`/start`  거래 시작    `/stop`  거래 중지\n"
        "`/pause`  신규 진입 일시정지\n"
        "`/stake 20`  포지션당 증거금 변경\n\n"
        "*INSIGHT*\n"
        "`/learn`  일일 복기\n"
        "`/learn_weekly`  주간 복기\n"
        "`/learn_monthly`  월간 복기\n\n"
        "*MORE*\n"
        "`/trades`  거래 내역    `/performance`  코인별 성과\n"
        "`/count`  슬롯 현황    `/locks`  진입 잠금\n\n"
        "_모든 금액은 USDT · 시간은 KST 기준_"
    )


Telegram._send_msg = _send_msg_ko
Telegram._stake_amount = _stake_amount
Telegram._learn_review = _learn_review
Telegram._daily_status = _daily_status
Telegram._startup_telegram = _startup_telegram_with_stake
Telegram._help = _help_with_stake
