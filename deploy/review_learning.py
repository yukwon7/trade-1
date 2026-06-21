"""Daily/weekly trade retrospectives for trade-1.

The script turns trade results plus 5m market candles into Korean retrospectives
and conservative rule candidates.  It is intentionally deterministic: no hidden
model, no external AI call, and no live-trading enablement.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from freqtrade_client import FtRestClient

from trade_learning import (
    connect,
    dumps,
    record_event,
    rebuild_signal_stats,
    upsert_learning_rule,
    upsert_trade_result,
    utcnow,
)


CONFIG_PATH = Path("/freqtrade/user_data/config.json")
DEFAULT_PAIRS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
    "DOGE/USDT:USDT",
    "ADA/USDT:USDT",
    "LINK/USDT:USDT",
]


def load_client() -> FtRestClient:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    api = config["api_server"]
    return FtRestClient(
        "http://127.0.0.1:8080",
        username=api["username"],
        password=api["password"],
    )


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        try:
            dt = datetime.strptime(str(value).split(".")[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def period_bounds(period: str, offset: int = 0) -> tuple[datetime, datetime, str]:
    now = datetime.now(timezone.utc)
    today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    if period == "daily":
        start = today - timedelta(days=1 + offset)
        end = start + timedelta(days=1)
        key = start.date().isoformat()
        return start, end, key
    if period == "monthly":
        first_this_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        month_end = first_this_month
        for _ in range(offset):
            month_end = month_end.replace(day=1) - timedelta(days=1)
            month_end = datetime(month_end.year, month_end.month, 1, tzinfo=timezone.utc)
        month_start_last = month_end - timedelta(days=1)
        month_start = datetime(month_start_last.year, month_start_last.month, 1, tzinfo=timezone.utc)
        return month_start, month_end, month_start.date().isoformat()
    week_start = today - timedelta(days=today.weekday() + 7 * offset)
    if offset == 0:
        week_start -= timedelta(days=7)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end, week_start.date().isoformat()


def sync_trades(client: FtRestClient) -> None:
    for trade in client.trades(limit=1000).get("trades", []):
        upsert_trade_result(trade)
    for trade in client.status():
        upsert_trade_result(trade)
    rebuild_signal_stats()


def load_closed_trades(start: datetime, end: datetime) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM trade_results
            WHERE is_open = 0
              AND close_date IS NOT NULL
            ORDER BY close_date
            """
        ).fetchall()
    trades = []
    for row in rows:
        trade = dict(row)
        close_dt = parse_dt(trade.get("close_date"))
        if close_dt and start <= close_dt < end:
            try:
                trade["raw"] = json.loads(trade.get("raw_json") or "{}")
            except Exception:
                trade["raw"] = {}
            trades.append(trade)
    return trades


def fetch_market_snapshot(client: FtRestClient, pairs: list[str]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for pair in pairs:
        try:
            data = client.pair_candles(pair, "5m", limit=288, columns=[])
            candles = data.get("data") or data.get("columns") or data.get("candles") or []
            parsed = parse_candles(candles)
            snapshot[pair] = summarize_candles(parsed)
        except Exception as exc:
            snapshot[pair] = {"error": str(exc)}
    return snapshot


def parse_candles(candles: Any) -> list[dict[str, float]]:
    parsed = []
    if isinstance(candles, dict) and all(isinstance(v, list) for v in candles.values()):
        keys = list(candles.keys())
        for values in zip(*[candles[k] for k in keys]):
            item = dict(zip(keys, values))
            parsed.append(
                {
                    "open": to_float(item.get("open")),
                    "high": to_float(item.get("high")),
                    "low": to_float(item.get("low")),
                    "close": to_float(item.get("close")),
                    "volume": to_float(item.get("volume")),
                }
            )
    elif isinstance(candles, list):
        for row in candles:
            if isinstance(row, dict):
                parsed.append(
                    {
                        "open": to_float(row.get("open")),
                        "high": to_float(row.get("high")),
                        "low": to_float(row.get("low")),
                        "close": to_float(row.get("close")),
                        "volume": to_float(row.get("volume")),
                    }
                )
            elif isinstance(row, (list, tuple)) and len(row) >= 6:
                parsed.append(
                    {
                        "open": to_float(row[1]),
                        "high": to_float(row[2]),
                        "low": to_float(row[3]),
                        "close": to_float(row[4]),
                        "volume": to_float(row[5]),
                    }
                )
    return [row for row in parsed if row["close"] > 0]


def summarize_candles(candles: list[dict[str, float]]) -> dict[str, Any]:
    if len(candles) < 2:
        return {"candle_count": len(candles)}
    first = candles[0]["close"]
    last = candles[-1]["close"]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    return {
        "candle_count": len(candles),
        "change_pct": round(((last - first) / first) * 100, 4) if first else 0,
        "range_pct": round(((max(highs) - min(lows)) / first) * 100, 4) if first else 0,
        "realized_vol_pct": round(statistics.pstdev(returns) * math.sqrt(len(returns)) * 100, 4)
        if len(returns) > 1
        else 0,
        "volume_ratio": round((volumes[-1] / statistics.mean(volumes)) if statistics.mean(volumes) else 0, 4),
        "last_close": last,
        "trend": "up" if last > first else "down" if last < first else "flat",
    }


def to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def analyze_contexts(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = (trade["pair"], trade["side"], trade["enter_tag"])
        grouped[key].append(trade)

    contexts = []
    for (pair, side, tag), items in grouped.items():
        profits = [to_float(t.get("profit_ratio")) for t in items]
        wins = sum(1 for p in profits if p > 0)
        losses = sum(1 for p in profits if p < 0)
        contexts.append(
            {
                "pair": pair,
                "side": side,
                "enter_tag": tag,
                "sample_count": len(items),
                "winrate": round(wins / len(items), 4) if items else 0,
                "loss_count": losses,
                "avg_profit": round(statistics.mean(profits), 6) if profits else 0,
                "total_profit": round(sum(profits), 6),
            }
        )
    best = sorted(contexts, key=lambda c: (c["avg_profit"], c["winrate"], c["sample_count"]), reverse=True)
    worst = sorted(contexts, key=lambda c: (c["avg_profit"], c["winrate"], -c["sample_count"]))
    return best[:5], worst[:5]


def build_daily_lessons(
    trades: list[dict[str, Any]], best: list[dict[str, Any]], worst: list[dict[str, Any]], market: dict[str, Any]
) -> list[str]:
    if not trades:
        return ["종료된 거래가 없어 오늘은 판단을 보류합니다."]
    lessons = []
    if best:
        top = best[0]
        lessons.append(
            f"좋았던 자리: {top['pair']} {top['side']} {top['enter_tag']} "
            f"평균손익 {top['avg_profit']:.4f}, 승률 {top['winrate']:.0%}."
        )
    if worst:
        bottom = worst[0]
        lessons.append(
            f"안 좋았던 자리: {bottom['pair']} {bottom['side']} {bottom['enter_tag']} "
            f"평균손익 {bottom['avg_profit']:.4f}, 승률 {bottom['winrate']:.0%}."
        )
    trend_counts = Counter(v.get("trend") for v in market.values() if isinstance(v, dict))
    if trend_counts:
        lessons.append(f"시장 배경: 5분봉 하루 흐름은 {dict(trend_counts)} 분포였습니다.")
    return lessons


def save_daily_review(key: str, trades: list[dict[str, Any]], market: dict[str, Any]) -> str:
    closed_count = len(trades)
    profits = [to_float(t.get("profit_ratio")) for t in trades]
    win_count = sum(1 for p in profits if p > 0)
    loss_count = sum(1 for p in profits if p < 0)
    total_profit = sum(profits)
    avg_profit = statistics.mean(profits) if profits else 0.0
    best, worst = analyze_contexts(trades)
    lessons = build_daily_lessons(trades, best, worst, market)
    summary = (
        f"일일 복기 {key}\n"
        f"- 종료 거래: {closed_count}건, 승/패: {win_count}/{loss_count}, "
        f"평균손익: {avg_profit:.4f}, 총손익: {total_profit:.4f}\n"
        + "\n".join(f"- {lesson}" for lesson in lessons)
    )

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO daily_reviews (
                review_date, created_at, trade_count, closed_count, win_count,
                loss_count, total_profit, avg_profit, best_context_json,
                worst_context_json, market_snapshot_json, lessons_json, summary_ko
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_date) DO UPDATE SET
                created_at = excluded.created_at,
                trade_count = excluded.trade_count,
                closed_count = excluded.closed_count,
                win_count = excluded.win_count,
                loss_count = excluded.loss_count,
                total_profit = excluded.total_profit,
                avg_profit = excluded.avg_profit,
                best_context_json = excluded.best_context_json,
                worst_context_json = excluded.worst_context_json,
                market_snapshot_json = excluded.market_snapshot_json,
                lessons_json = excluded.lessons_json,
                summary_ko = excluded.summary_ko
            """,
            (
                key,
                utcnow(),
                len(trades),
                closed_count,
                win_count,
                loss_count,
                total_profit,
                avg_profit,
                dumps(best),
                dumps(worst),
                dumps(market),
                dumps(lessons),
                summary,
            ),
        )
        conn.commit()
    record_event("daily_review", f"daily review {key}", {"closed": closed_count})
    return summary


def load_daily_reviews(start: datetime, end: datetime) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM daily_reviews
            WHERE review_date >= ? AND review_date < ?
            ORDER BY review_date
            """,
            (start.date().isoformat(), end.date().isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]


def context_counter(rows: list[dict[str, Any]], column: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        try:
            contexts = json.loads(row[column] or "[]")
        except Exception:
            contexts = []
        for ctx in contexts:
            key = (ctx.get("pair"), ctx.get("side"), ctx.get("enter_tag"))
            counter[key] += 1
    return counter


def save_weekly_review(start: datetime, end: datetime, key: str) -> str:
    daily_rows = load_daily_reviews(start, end)
    trades = load_closed_trades(start, end)
    profits = [to_float(t.get("profit_ratio")) for t in trades]
    win_count = sum(1 for p in profits if p > 0)
    loss_count = sum(1 for p in profits if p < 0)
    total_profit = sum(profits)
    avg_profit = statistics.mean(profits) if profits else 0.0
    good = context_counter(daily_rows, "best_context_json")
    bad = context_counter(daily_rows, "worst_context_json")
    common_good = counter_to_contexts(good)
    common_bad = counter_to_contexts(bad)
    candidates = build_rule_candidates(trades)
    for candidate in candidates:
        upsert_learning_rule(**candidate)

    week_end_key = (end - timedelta(days=1)).date().isoformat()
    summary = (
        f"주간 복기 {key}~{week_end_key}\n"
        f"- 일일 복기: {len(daily_rows)}일, 종료 거래: {len(trades)}건, "
        f"승/패: {win_count}/{loss_count}, 평균손익: {avg_profit:.4f}, 총손익: {total_profit:.4f}\n"
        f"- 반복적으로 좋았던 맥락: {format_contexts(common_good)}\n"
        f"- 반복적으로 안 좋았던 맥락: {format_contexts(common_bad)}\n"
        f"- 생성/갱신한 보수 규칙 후보: {len(candidates)}개"
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO weekly_reviews (
                week_start, week_end, created_at, day_count, trade_count,
                closed_count, win_count, loss_count, total_profit, avg_profit,
                common_good_json, common_bad_json, rule_candidates_json, summary_ko
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET
                week_end = excluded.week_end,
                created_at = excluded.created_at,
                day_count = excluded.day_count,
                trade_count = excluded.trade_count,
                closed_count = excluded.closed_count,
                win_count = excluded.win_count,
                loss_count = excluded.loss_count,
                total_profit = excluded.total_profit,
                avg_profit = excluded.avg_profit,
                common_good_json = excluded.common_good_json,
                common_bad_json = excluded.common_bad_json,
                rule_candidates_json = excluded.rule_candidates_json,
                summary_ko = excluded.summary_ko
            """,
            (
                key,
                week_end_key,
                utcnow(),
                len(daily_rows),
                len(trades),
                len(trades),
                win_count,
                loss_count,
                total_profit,
                avg_profit,
                dumps(common_good),
                dumps(common_bad),
                dumps(candidates),
                summary,
            ),
        )
        conn.commit()
    record_event("weekly_review", f"weekly review {key}", {"closed": len(trades), "rules": len(candidates)})
    return summary


def load_weekly_reviews(start: datetime, end: datetime) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM weekly_reviews
            WHERE week_start >= ? AND week_start < ?
            ORDER BY week_start
            """,
            (start.date().isoformat(), end.date().isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]


def save_monthly_review(start: datetime, end: datetime, key: str) -> str:
    weekly_rows = load_weekly_reviews(start, end)
    daily_rows = load_daily_reviews(start, end)
    trades = load_closed_trades(start, end)
    profits = [to_float(t.get("profit_ratio")) for t in trades]
    win_count = sum(1 for p in profits if p > 0)
    loss_count = sum(1 for p in profits if p < 0)
    total_profit = sum(profits)
    avg_profit = statistics.mean(profits) if profits else 0.0

    good = context_counter(daily_rows, "best_context_json")
    bad = context_counter(daily_rows, "worst_context_json")
    for row in weekly_rows:
        try:
            weekly_good = json.loads(row.get("common_good_json") or "[]")
            weekly_bad = json.loads(row.get("common_bad_json") or "[]")
        except Exception:
            weekly_good, weekly_bad = [], []
        for ctx in weekly_good:
            good[(ctx.get("pair"), ctx.get("side"), ctx.get("enter_tag"))] += int(ctx.get("days") or 1)
        for ctx in weekly_bad:
            bad[(ctx.get("pair"), ctx.get("side"), ctx.get("enter_tag"))] += int(ctx.get("days") or 1)

    common_good = counter_to_contexts(good)
    common_bad = counter_to_contexts(bad)
    candidates = build_rule_candidates(trades)
    monthly_candidates = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate["source"] = "monthly_review"
        candidate["confidence"] = min(0.98, float(candidate["confidence"]) + 0.05)
        candidate["reason_ko"] = candidate["reason_ko"].replace("주간 복기", "월간 복기")
        monthly_candidates.append(candidate)
        upsert_learning_rule(**candidate)

    month_end_key = (end - timedelta(days=1)).date().isoformat()
    summary = (
        f"월간 복기 {key}~{month_end_key}\n"
        f"- 주간 복기: {len(weekly_rows)}주, 일일 복기: {len(daily_rows)}일, 종료 거래: {len(trades)}건\n"
        f"- 승/패: {win_count}/{loss_count}, 평균손익: {avg_profit:.4f}, 총손익: {total_profit:.4f}\n"
        f"- 월간 반복 강점: {format_contexts(common_good)}\n"
        f"- 월간 반복 약점: {format_contexts(common_bad)}\n"
        f"- 생성/갱신한 월간 보수 규칙 후보: {len(monthly_candidates)}개"
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO monthly_reviews (
                month_start, month_end, created_at, week_count, day_count,
                trade_count, closed_count, win_count, loss_count, total_profit,
                avg_profit, common_good_json, common_bad_json,
                rule_candidates_json, summary_ko
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month_start) DO UPDATE SET
                month_end = excluded.month_end,
                created_at = excluded.created_at,
                week_count = excluded.week_count,
                day_count = excluded.day_count,
                trade_count = excluded.trade_count,
                closed_count = excluded.closed_count,
                win_count = excluded.win_count,
                loss_count = excluded.loss_count,
                total_profit = excluded.total_profit,
                avg_profit = excluded.avg_profit,
                common_good_json = excluded.common_good_json,
                common_bad_json = excluded.common_bad_json,
                rule_candidates_json = excluded.rule_candidates_json,
                summary_ko = excluded.summary_ko
            """,
            (
                key,
                month_end_key,
                utcnow(),
                len(weekly_rows),
                len(daily_rows),
                len(trades),
                len(trades),
                win_count,
                loss_count,
                total_profit,
                avg_profit,
                dumps(common_good),
                dumps(common_bad),
                dumps(monthly_candidates),
                summary,
            ),
        )
        conn.commit()
    record_event(
        "monthly_review",
        f"monthly review {key}",
        {"closed": len(trades), "rules": len(monthly_candidates)},
    )
    return summary


def counter_to_contexts(counter: Counter) -> list[dict[str, Any]]:
    result = []
    for (pair, side, tag), count in counter.most_common(5):
        result.append({"pair": pair, "side": side, "enter_tag": tag, "days": count})
    return result


def format_contexts(contexts: list[dict[str, Any]]) -> str:
    if not contexts:
        return "아직 없음"
    return ", ".join(
        f"{c['pair']} {c['side']} {c['enter_tag']}({c['days']}일)" for c in contexts
    )


def build_rule_candidates(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade.get("source") != "auto":
            continue
        grouped[(trade["pair"], trade["side"], trade["enter_tag"])].append(trade)

    candidates = []
    for (pair, side, tag), items in grouped.items():
        if len(items) < 6:
            continue
        profits = [to_float(t.get("profit_ratio")) for t in items]
        wins = sum(1 for p in profits if p > 0)
        winrate = wins / len(items)
        avg_profit = statistics.mean(profits)
        if winrate < 0.35 and avg_profit < 0:
            confidence = min(0.95, 0.45 + len(items) / 40 + abs(avg_profit) * 5)
            candidates.append(
                {
                    "source": "weekly_review",
                    "rule_type": "bad_context",
                    "scope": "pair",
                    "pair": pair,
                    "side": side,
                    "enter_tag": tag,
                    "condition": {"type": "signal_context"},
                    "action": "block_entry",
                    "confidence": confidence,
                    "sample_count": len(items),
                    "winrate": winrate,
                    "avg_profit": avg_profit,
                    "enabled": True,
                    "reason_ko": (
                        f"주간 복기 기준 {pair} {side} {tag}는 표본 {len(items)}건, "
                        f"승률 {winrate:.0%}, 평균손익 {avg_profit:.4f}로 약해 자동 진입을 보류"
                    ),
                }
            )
        positive = [p for p in profits if p > 0]
        negative = [p for p in profits if p < 0]
        if len(positive) >= 3 and winrate >= 0.55 and avg_profit > 0:
            threshold = max(0.01, min(0.08, statistics.median(positive) * 0.75))
            candidates.append(
                {
                    "source": "weekly_review",
                    "rule_type": "take_profit_timing",
                    "scope": "pair",
                    "pair": pair,
                    "side": side,
                    "enter_tag": tag,
                    "condition": {"type": "profit_threshold", "profit_ratio": threshold},
                    "action": "take_profit",
                    "confidence": min(0.92, 0.40 + len(items) / 45 + winrate / 5),
                    "sample_count": len(items),
                    "winrate": winrate,
                    "avg_profit": avg_profit,
                    "enabled": True,
                    "reason_ko": (
                        f"주간 복기 기준 {pair} {side} {tag}는 이익 거래가 반복되어 "
                        f"수익률 {threshold:.4f} 부근에서 학습 익절 후보"
                    ),
                }
            )
        if len(negative) >= 3 and avg_profit < 0:
            threshold = min(-0.05, max(-0.08, statistics.median(negative) * 0.85))
            candidates.append(
                {
                    "source": "weekly_review",
                    "rule_type": "stop_loss_timing",
                    "scope": "pair",
                    "pair": pair,
                    "side": side,
                    "enter_tag": tag,
                    "condition": {"type": "loss_threshold", "profit_ratio": threshold},
                    "action": "cut_loss",
                    "confidence": min(0.90, 0.40 + len(items) / 50 + abs(avg_profit) * 4),
                    "sample_count": len(items),
                    "winrate": winrate,
                    "avg_profit": avg_profit,
                    "enabled": True,
                    "reason_ko": (
                        f"주간 복기 기준 {pair} {side} {tag}는 손실 거래가 반복되어 "
                        f"수익률 {threshold:.4f} 부근에서 학습 손절 후보"
                    ),
                }
            )
    return candidates


def run_daily(offset: int = 0) -> str:
    client = load_client()
    sync_trades(client)
    start, end, key = period_bounds("daily", offset)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    pairs = config.get("exchange", {}).get("pair_whitelist") or DEFAULT_PAIRS
    trades = load_closed_trades(start, end)
    market = fetch_market_snapshot(client, pairs)
    return save_daily_review(key, trades, market)


def run_weekly(offset: int = 0) -> str:
    client = load_client()
    sync_trades(client)
    start, end, key = period_bounds("weekly", offset)
    return save_weekly_review(start, end, key)


def run_monthly(offset: int = 0) -> str:
    client = load_client()
    sync_trades(client)
    start, end, key = period_bounds("monthly", offset)
    return save_monthly_review(start, end, key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["daily", "weekly", "monthly"], default="daily")
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if args.period == "daily":
        print(run_daily(args.offset))
    elif args.period == "weekly":
        print(run_weekly(args.offset))
    else:
        print(run_monthly(args.offset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
