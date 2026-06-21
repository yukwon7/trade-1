"""Persistent trade-decision/result learning store for trade-1.

This module is intentionally conservative:
- It never disables manual/forced entries.
- It only blocks an automatic signal after enough closed samples show poor results.
- All database errors are safe to ignore from the strategy layer.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DB_PATH = os.getenv(
    "TRADE_LEARNING_DB",
    "/freqtrade/user_data/learning/trade_learning.sqlite",
)
MIN_PAIR_SAMPLES = int(os.getenv("TRADE_LEARNING_MIN_PAIR_SAMPLES", "20"))
MIN_GLOBAL_SAMPLES = int(os.getenv("TRADE_LEARNING_MIN_GLOBAL_SAMPLES", "30"))
MIN_WINRATE = float(os.getenv("TRADE_LEARNING_MIN_WINRATE", "0.35"))
MIN_REVIEW_SAMPLES = int(os.getenv("TRADE_LEARNING_MIN_REVIEW_SAMPLES", "6"))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=_json_default)


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entry_decisions (
            decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            enter_tag TEXT NOT NULL,
            strategy TEXT,
            source TEXT NOT NULL,
            allowed INTEGER NOT NULL,
            blocked_reason TEXT,
            rate REAL,
            amount REAL,
            leverage REAL,
            indicators_json TEXT NOT NULL,
            conditions_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_entry_decisions_lookup
            ON entry_decisions(pair, side, enter_tag, created_at);

        CREATE TABLE IF NOT EXISTS trade_results (
            trade_id INTEGER PRIMARY KEY,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            strategy TEXT,
            enter_tag TEXT NOT NULL,
            source TEXT NOT NULL,
            is_open INTEGER NOT NULL,
            open_date TEXT,
            close_date TEXT,
            open_rate REAL,
            close_rate REAL,
            stake_amount REAL,
            leverage REAL,
            profit_ratio REAL,
            profit_pct REAL,
            profit_abs REAL,
            exit_reason TEXT,
            duration_s INTEGER,
            result_label TEXT NOT NULL,
            entry_reason TEXT NOT NULL,
            result_reason TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trade_results_stats
            ON trade_results(pair, side, enter_tag, is_open);

        CREATE TABLE IF NOT EXISTS signal_stats (
            scope TEXT NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            enter_tag TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            win_count INTEGER NOT NULL,
            loss_count INTEGER NOT NULL,
            avg_profit REAL NOT NULL,
            total_profit REAL NOT NULL,
            winrate REAL NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope, pair, side, enter_tag)
        );

        CREATE TABLE IF NOT EXISTS learning_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_reviews (
            review_date TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            trade_count INTEGER NOT NULL,
            closed_count INTEGER NOT NULL,
            win_count INTEGER NOT NULL,
            loss_count INTEGER NOT NULL,
            total_profit REAL NOT NULL,
            avg_profit REAL NOT NULL,
            best_context_json TEXT NOT NULL,
            worst_context_json TEXT NOT NULL,
            market_snapshot_json TEXT NOT NULL,
            lessons_json TEXT NOT NULL,
            summary_ko TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS weekly_reviews (
            week_start TEXT PRIMARY KEY,
            week_end TEXT NOT NULL,
            created_at TEXT NOT NULL,
            day_count INTEGER NOT NULL,
            trade_count INTEGER NOT NULL,
            closed_count INTEGER NOT NULL,
            win_count INTEGER NOT NULL,
            loss_count INTEGER NOT NULL,
            total_profit REAL NOT NULL,
            avg_profit REAL NOT NULL,
            common_good_json TEXT NOT NULL,
            common_bad_json TEXT NOT NULL,
            rule_candidates_json TEXT NOT NULL,
            summary_ko TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monthly_reviews (
            month_start TEXT PRIMARY KEY,
            month_end TEXT NOT NULL,
            created_at TEXT NOT NULL,
            week_count INTEGER NOT NULL,
            day_count INTEGER NOT NULL,
            trade_count INTEGER NOT NULL,
            closed_count INTEGER NOT NULL,
            win_count INTEGER NOT NULL,
            loss_count INTEGER NOT NULL,
            total_profit REAL NOT NULL,
            avg_profit REAL NOT NULL,
            common_good_json TEXT NOT NULL,
            common_bad_json TEXT NOT NULL,
            rule_candidates_json TEXT NOT NULL,
            summary_ko TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS learning_rules (
            rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            enter_tag TEXT NOT NULL,
            condition_json TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            winrate REAL NOT NULL,
            avg_profit REAL NOT NULL,
            enabled INTEGER NOT NULL,
            reason_ko TEXT NOT NULL,
            UNIQUE(source, rule_type, scope, pair, side, enter_tag, condition_json, action)
        );
        """
    )
    conn.commit()


def normalize_tag(enter_tag: str | None) -> str:
    return (enter_tag or "unknown").strip() or "unknown"


def infer_source(enter_tag: str | None) -> str:
    tag = normalize_tag(enter_tag)
    automatic_tags = {
        "trend_adx20_long",
        "trend_adx20_short",
        "recent_bull_cross",
        "recent_bear_cross",
        "macd_momentum_long",
        "macd_momentum_short",
        "macd_loose_long",
        "macd_loose_short",
        "macd_active_long",
        "macd_active_short",
        "macd_responsive_long",
        "macd_responsive_short",
    }
    return "auto" if tag in automatic_tags else "manual"


def entry_reason(pair: str, side: str, enter_tag: str | None) -> str:
    tag = normalize_tag(enter_tag)
    if tag in {"trend_adx20_long", "recent_bull_cross"}:
        return (
            f"{pair} long: 5분 종가가 1시간 SMA 위, 단기 EMA가 장기 EMA 위, "
            "ADX가 기준값 이상이라 상승 추세 신호로 진입"
        )
    if tag in {"trend_adx20_short", "recent_bear_cross"}:
        return (
            f"{pair} short: 5분 종가가 1시간 SMA 아래, 단기 EMA가 장기 EMA 아래, "
            "ADX가 기준값 이상이라 하락 추세 신호로 진입"
        )
    if tag == "macd_momentum_long":
        return f"{pair} long: MACD 상향 교차와 EMA200·RSI·ADX 상승 모멘텀이 일치해 진입"
    if tag == "macd_momentum_short":
        return f"{pair} short: MACD 하향 교차와 EMA200·RSI·ADX 하락 모멘텀이 일치해 진입"
    if tag == "macd_loose_long":
        return f"{pair} long: MACD 상향 교차와 EMA150·완화 RSI·ADX 상승 조건이 일치해 진입"
    if tag == "macd_loose_short":
        return f"{pair} short: MACD 하향 교차와 EMA150·완화 RSI·ADX 하락 조건이 일치해 진입"
    if tag == "macd_active_long":
        return f"{pair} long: 5분봉 MACD 상향 교차와 EMA200·RSI·ADX 30 조건이 일치해 진입"
    if tag == "macd_active_short":
        return f"{pair} short: 5분봉 MACD 하향 교차와 EMA200·RSI·ADX 30 조건이 일치해 진입"
    if tag == "macd_responsive_long":
        return f"{pair} long: 5분봉 MACD 상승 모멘텀과 EMA200·RSI·ADX 24 조건이 지속돼 진입"
    if tag == "macd_responsive_short":
        return f"{pair} short: 5분봉 MACD 하락 모멘텀과 EMA200·RSI·ADX 24 조건이 지속돼 진입"
    if tag.startswith(("force", "manual", "fill", "refill", "initial")):
        return f"{pair} {side}: 사용자가 수동/강제 진입한 포지션"
    return f"{pair} {side}: enter_tag={tag} 신호로 진입"


def result_label(profit_abs: float | None, profit_ratio: float | None) -> str:
    value = profit_abs if profit_abs is not None else profit_ratio
    if value is None:
        return "open"
    if value > 0:
        return "win"
    if value < 0:
        return "loss"
    return "breakeven"


def result_reason(trade: dict[str, Any]) -> str:
    if trade.get("is_open"):
        return "아직 열린 포지션이라 최종 손익 원인은 미확정"
    reason = str(trade.get("exit_reason") or "unknown")
    label = result_label(_to_float(trade.get("profit_abs")), _to_float(trade.get("profit_ratio")))
    prefix = "이익" if label == "win" else "손실" if label == "loss" else "본전"
    if "stop" in reason:
        return f"{prefix}: 손절/스탑 계열 청산({reason})으로 종료"
    if "roi" in reason:
        return f"{prefix}: ROI 목표 또는 익절 조건({reason})으로 종료"
    if "exit_signal" in reason:
        return f"{prefix}: 전략의 추세/ADX 이탈 청산 신호({reason})로 종료"
    if "force" in reason:
        return f"{prefix}: 사용자의 강제 청산({reason})으로 종료"
    return f"{prefix}: Freqtrade 청산 사유 {reason}으로 종료"


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def record_entry_decision(
    *,
    pair: str,
    side: str,
    enter_tag: str | None,
    strategy: str | None,
    source: str,
    allowed: bool,
    blocked_reason: str | None,
    rate: float | None,
    amount: float | None,
    leverage: float | None,
    indicators: dict[str, Any],
    conditions: dict[str, Any],
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO entry_decisions (
                created_at, pair, side, enter_tag, strategy, source, allowed,
                blocked_reason, rate, amount, leverage, indicators_json, conditions_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utcnow(),
                pair,
                side,
                normalize_tag(enter_tag),
                strategy,
                source,
                1 if allowed else 0,
                blocked_reason,
                rate,
                amount,
                leverage,
                dumps(indicators),
                dumps(conditions),
            ),
        )
        conn.commit()


def should_block_signal(pair: str, side: str, enter_tag: str | None) -> tuple[bool, str | None]:
    tag = normalize_tag(enter_tag)
    with connect() as conn:
        rule = _matching_block_rule(conn, pair, side, tag)
        if rule:
            return True, str(rule["reason_ko"])

        exact = conn.execute(
            """
            SELECT sample_count, winrate, avg_profit
            FROM signal_stats
            WHERE scope = 'pair' AND pair = ? AND side = ? AND enter_tag = ?
            """,
            (pair, side, tag),
        ).fetchone()
        if exact and _is_bad_stats(exact, MIN_PAIR_SAMPLES):
            return (
                True,
                f"pair stats weak: samples={exact['sample_count']} "
                f"winrate={exact['winrate']:.2f} avg_profit={exact['avg_profit']:.5f}",
            )

        global_row = conn.execute(
            """
            SELECT sample_count, winrate, avg_profit
            FROM signal_stats
            WHERE scope = 'global' AND pair = '*' AND side = ? AND enter_tag = ?
            """,
            (side, tag),
        ).fetchone()
        if global_row and _is_bad_stats(global_row, MIN_GLOBAL_SAMPLES):
            return (
                True,
                f"global stats weak: samples={global_row['sample_count']} "
                f"winrate={global_row['winrate']:.2f} avg_profit={global_row['avg_profit']:.5f}",
            )
    return False, None


def _matching_block_rule(
    conn: sqlite3.Connection, pair: str, side: str, enter_tag: str
) -> sqlite3.Row | None:
    rules = conn.execute(
        """
        SELECT *
        FROM learning_rules
        WHERE enabled = 1
          AND action = 'block_entry'
          AND side IN (?, '*')
          AND enter_tag IN (?, '*')
          AND pair IN (?, '*')
        ORDER BY confidence DESC, sample_count DESC, updated_at DESC
        LIMIT 20
        """,
        (side, enter_tag, pair),
    ).fetchall()
    for rule in rules:
        try:
            condition = json.loads(rule["condition_json"])
        except Exception:
            condition = {}
        if condition.get("type") in (None, "signal_context"):
            return rule
    return None


def get_exit_decision(
    pair: str,
    side: str,
    enter_tag: str | None,
    current_profit: float,
) -> tuple[str | None, str | None]:
    tag = normalize_tag(enter_tag)
    with connect() as conn:
        rules = conn.execute(
            """
            SELECT *
            FROM learning_rules
            WHERE enabled = 1
              AND action IN ('take_profit', 'cut_loss')
              AND side IN (?, '*')
              AND enter_tag IN (?, '*')
              AND pair IN (?, '*')
            ORDER BY confidence DESC, sample_count DESC, updated_at DESC
            LIMIT 20
            """,
            (side, tag, pair),
        ).fetchall()
    for rule in rules:
        try:
            condition = json.loads(rule["condition_json"])
        except Exception:
            condition = {}
        threshold = _to_float(condition.get("profit_ratio"))
        if threshold is None:
            continue
        if rule["action"] == "take_profit" and current_profit >= threshold:
            return "learning_take_profit", str(rule["reason_ko"])
        if rule["action"] == "cut_loss" and current_profit <= threshold:
            return "learning_cut_loss", str(rule["reason_ko"])
    return None, None


def _is_bad_stats(row: sqlite3.Row, min_samples: int) -> bool:
    return (
        int(row["sample_count"]) >= min_samples
        and float(row["winrate"]) < MIN_WINRATE
        and float(row["avg_profit"]) < 0
    )


def upsert_trade_result(trade: dict[str, Any]) -> bool:
    trade_id = _to_int(trade.get("trade_id"))
    if trade_id is None:
        return False

    pair = str(trade.get("pair") or "unknown")
    side = "short" if trade.get("is_short") else "long"
    tag = normalize_tag(trade.get("enter_tag"))
    source = infer_source(tag)
    profit_ratio = _to_float(trade.get("profit_ratio") or trade.get("close_profit"))
    profit_pct = _to_float(trade.get("profit_pct") or trade.get("close_profit_pct"))
    profit_abs = _to_float(trade.get("profit_abs") or trade.get("close_profit_abs"))
    label = "open" if trade.get("is_open") else result_label(profit_abs, profit_ratio)

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_results (
                trade_id, pair, side, strategy, enter_tag, source, is_open,
                open_date, close_date, open_rate, close_rate, stake_amount, leverage,
                profit_ratio, profit_pct, profit_abs, exit_reason, duration_s,
                result_label, entry_reason, result_reason, synced_at, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                pair = excluded.pair,
                side = excluded.side,
                strategy = excluded.strategy,
                enter_tag = excluded.enter_tag,
                source = excluded.source,
                is_open = excluded.is_open,
                open_date = excluded.open_date,
                close_date = excluded.close_date,
                open_rate = excluded.open_rate,
                close_rate = excluded.close_rate,
                stake_amount = excluded.stake_amount,
                leverage = excluded.leverage,
                profit_ratio = excluded.profit_ratio,
                profit_pct = excluded.profit_pct,
                profit_abs = excluded.profit_abs,
                exit_reason = excluded.exit_reason,
                duration_s = excluded.duration_s,
                result_label = excluded.result_label,
                entry_reason = excluded.entry_reason,
                result_reason = excluded.result_reason,
                synced_at = excluded.synced_at,
                raw_json = excluded.raw_json
            """,
            (
                trade_id,
                pair,
                side,
                trade.get("strategy"),
                tag,
                source,
                1 if trade.get("is_open") else 0,
                trade.get("open_date") or trade.get("open_fill_date"),
                trade.get("close_date"),
                _to_float(trade.get("open_rate")),
                _to_float(trade.get("close_rate")),
                _to_float(trade.get("stake_amount")),
                _to_float(trade.get("leverage")),
                profit_ratio,
                profit_pct,
                profit_abs,
                trade.get("exit_reason"),
                _to_int(trade.get("trade_duration_s")),
                label,
                entry_reason(pair, side, tag),
                result_reason(trade),
                utcnow(),
                dumps(trade),
            ),
        )
        conn.commit()
    return True


def rebuild_signal_stats() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM signal_stats")
        queries = [
            (
                "pair",
                """
                SELECT pair, side, enter_tag,
                       COUNT(*) AS sample_count,
                       SUM(CASE WHEN result_label = 'win' THEN 1 ELSE 0 END) AS win_count,
                       SUM(CASE WHEN result_label = 'loss' THEN 1 ELSE 0 END) AS loss_count,
                       AVG(COALESCE(profit_ratio, profit_abs, 0)) AS avg_profit,
                       SUM(COALESCE(profit_ratio, profit_abs, 0)) AS total_profit
                FROM trade_results
                WHERE is_open = 0
                  AND source = 'auto'
                  AND result_label IN ('win', 'loss', 'breakeven')
                GROUP BY pair, side, enter_tag
                """,
            ),
            (
                "global",
                """
                SELECT '*' AS pair, side, enter_tag,
                       COUNT(*) AS sample_count,
                       SUM(CASE WHEN result_label = 'win' THEN 1 ELSE 0 END) AS win_count,
                       SUM(CASE WHEN result_label = 'loss' THEN 1 ELSE 0 END) AS loss_count,
                       AVG(COALESCE(profit_ratio, profit_abs, 0)) AS avg_profit,
                       SUM(COALESCE(profit_ratio, profit_abs, 0)) AS total_profit
                FROM trade_results
                WHERE is_open = 0
                  AND source = 'auto'
                  AND result_label IN ('win', 'loss', 'breakeven')
                GROUP BY side, enter_tag
                """,
            ),
        ]
        for scope, query in queries:
            rows = conn.execute(query).fetchall()
            for row in rows:
                sample_count = int(row["sample_count"] or 0)
                win_count = int(row["win_count"] or 0)
                winrate = (win_count / sample_count) if sample_count else 0.0
                conn.execute(
                    """
                    INSERT INTO signal_stats (
                        scope, pair, side, enter_tag, sample_count, win_count,
                        loss_count, avg_profit, total_profit, winrate, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scope,
                        row["pair"],
                        row["side"],
                        row["enter_tag"],
                        sample_count,
                        win_count,
                        int(row["loss_count"] or 0),
                        float(row["avg_profit"] or 0.0),
                        float(row["total_profit"] or 0.0),
                        winrate,
                        utcnow(),
                    ),
                )
        conn.commit()


def record_event(event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO learning_events(created_at, event_type, message, data_json)
            VALUES (?, ?, ?, ?)
            """,
            (utcnow(), event_type, message, dumps(data)),
        )
        conn.commit()


def upsert_learning_rule(
    *,
    source: str,
    rule_type: str,
    scope: str,
    pair: str,
    side: str,
    enter_tag: str,
    condition: dict[str, Any],
    action: str,
    confidence: float,
    sample_count: int,
    winrate: float,
    avg_profit: float,
    enabled: bool,
    reason_ko: str,
) -> None:
    condition_json = dumps(condition)
    now = utcnow()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO learning_rules (
                created_at, updated_at, source, rule_type, scope, pair, side,
                enter_tag, condition_json, action, confidence, sample_count,
                winrate, avg_profit, enabled, reason_ko
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, rule_type, scope, pair, side, enter_tag, condition_json, action)
            DO UPDATE SET
                updated_at = excluded.updated_at,
                confidence = excluded.confidence,
                sample_count = excluded.sample_count,
                winrate = excluded.winrate,
                avg_profit = excluded.avg_profit,
                enabled = excluded.enabled,
                reason_ko = excluded.reason_ko
            """,
            (
                now,
                now,
                source,
                rule_type,
                scope,
                pair,
                side,
                normalize_tag(enter_tag),
                condition_json,
                action,
                confidence,
                sample_count,
                winrate,
                avg_profit,
                1 if enabled else 0,
                reason_ko,
            ),
        )
        conn.commit()


def latest_review_summary(kind: str = "daily") -> str:
    if kind == "monthly":
        table = "monthly_reviews"
        order_col = "month_start"
    elif kind == "weekly":
        table = "weekly_reviews"
        order_col = "week_start"
    else:
        table = "daily_reviews"
        order_col = "review_date"
    with connect() as conn:
        row = conn.execute(
            f"SELECT summary_ko FROM {table} ORDER BY {order_col} DESC LIMIT 1"
        ).fetchone()
        return row["summary_ko"] if row else "아직 저장된 복기 리포트가 없습니다."
