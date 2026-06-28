from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from indicators import adx, atr, ema, volume_ratio
from models import StrategySignal
from strategies.base import BaseStrategy
from strategies.utils import bollinger, closes, heikin_ashi, macd, rolling_vwap, rsi_values, sma


@dataclass(frozen=True)
class ChartRegime:
    name: str
    bias: str
    trend: str
    volatility: str
    volume: str
    score: float
    tags: tuple[str, ...]


class CatalogStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str,
        name: str,
        template: str,
        regimes: tuple[str, ...],
        *,
        leverage: int = 3,
        stop_loss_pct: float = 0.008,
        take_profit_pct: float | None = 0.015,
        params: dict[str, Any] | None = None,
        source: str = "public_common",
    ):
        self.strategy_id = strategy_id
        self.name = name
        self.template = template
        self.regimes = regimes
        self.leverage = min(3, max(1, leverage))
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.params = params or {}
        self.source = source
        self.minimum_candles = int(self.params.get("minimum_candles", 120))

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        if min(len(candles_5m), len(candles_15m)) < self.minimum_candles:
            return None
        regime = analyze_regime(candles_5m, candles_15m)
        if regime.name not in self.regimes and "ANY" not in self.regimes:
            return None
        method = getattr(self, f"_template_{self.template}", None)
        if method is None:
            return None
        signal = method(symbol, candles_5m, candles_15m, regime)
        if signal is None:
            return None
        signal.metadata.update({
            "router_regime": regime.name,
            "router_score": round(regime.score, 3),
            "router_tags": list(regime.tags),
            "template": self.template,
            "source": self.source,
        })
        return signal

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        regime = analyze_regime(candles_5m, candles_15m)
        values = closes(candles_5m)
        ema20 = ema(values, 20)
        ema50 = ema(values, 50)
        rsi = rsi_values(candles_5m)
        if position.direction == "LONG":
            if ema20[-1] < ema50[-1]:
                return "ROUTER_TREND_FLIP"
            if rsi[-1] > float(self.params.get("hard_long_rsi", 76)):
                return "ROUTER_RSI_EXHAUSTION"
            if regime.name in {"CHOP_HIGH_VOL", "BEAR_TREND"}:
                return "ROUTER_REGIME_FLIP"
        else:
            if ema20[-1] > ema50[-1]:
                return "ROUTER_TREND_FLIP"
            if rsi[-1] < float(self.params.get("hard_short_rsi", 24)):
                return "ROUTER_RSI_EXHAUSTION"
            if regime.name in {"CHOP_HIGH_VOL", "BULL_TREND"}:
                return "ROUTER_REGIME_FLIP"
        return None

    def _template_ema_pullback(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        fast = ema(values, int(self.params.get("fast", 9)))
        slow = ema(values, int(self.params.get("slow", 21)))
        macro = ema(closes(candles_15m), int(self.params.get("macro", 55)))
        rsi = rsi_values(candles_5m)
        last, prev = candles_5m[-1], candles_5m[-2]
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        min_vol = float(self.params.get("volume", 1.05))
        if fast[-1] > slow[-1] and values[-1] > macro[-1] and prev.low <= fast[-2] and last.close > fast[-1] and 48 <= rsi[-1] <= 68 and vol >= min_vol:
            return self.signal(symbol, "LONG", last.close, "EMA pullback continuation", {"score": 73 + vol})
        if fast[-1] < slow[-1] and values[-1] < macro[-1] and prev.high >= fast[-2] and last.close < fast[-1] and 32 <= rsi[-1] <= 52 and vol >= min_vol:
            return self.signal(symbol, "SHORT", last.close, "EMA pullback continuation", {"score": 73 + vol})
        return None

    def _template_ema_breakout(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        fast = ema(values, int(self.params.get("fast", 9)))
        slow = ema(values, int(self.params.get("slow", 21)))
        prior = candles_5m[-int(self.params.get("lookback", 20)) - 1 : -1]
        last = candles_5m[-1]
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        threshold = float(self.params.get("volume", 1.35))
        if not prior or vol < threshold:
            return None
        if fast[-1] > slow[-1] and last.close > max(item.high for item in prior):
            return self.signal(symbol, "LONG", last.close, "EMA trend breakout", {"score": 76 + vol})
        if fast[-1] < slow[-1] and last.close < min(item.low for item in prior):
            return self.signal(symbol, "SHORT", last.close, "EMA trend breakdown", {"score": 76 + vol})
        return None

    def _template_macd_momentum(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        line, signal_line, hist = macd(values)
        rsi = rsi_values(candles_5m)
        last = candles_5m[-1]
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        if hist[-2] <= 0 < hist[-1] and line[-1] > signal_line[-1] and rsi[-1] > 50 and vol >= float(self.params.get("volume", 1.0)):
            return self.signal(symbol, "LONG", last.close, "MACD histogram flip with RSI confirmation", {"score": 72 + vol})
        if hist[-2] >= 0 > hist[-1] and line[-1] < signal_line[-1] and rsi[-1] < 50 and vol >= float(self.params.get("volume", 1.0)):
            return self.signal(symbol, "SHORT", last.close, "MACD histogram flip with RSI confirmation", {"score": 72 + vol})
        return None

    def _template_bb_mean_revert(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        middle, upper, lower, _ = bollinger(values, int(self.params.get("period", 20)), float(self.params.get("deviation", 2.0)))
        rsi = rsi_values(candles_5m)
        last = candles_5m[-1]
        if last.close < lower[-1] and rsi[-1] <= float(self.params.get("long_rsi", 32)) and regime.name in {"RANGE_LOW_VOL", "RANGE_NORMAL"}:
            return self.signal(symbol, "LONG", last.close, "Bollinger lower band mean reversion", {"score": 70, "target": middle[-1]})
        if last.close > upper[-1] and rsi[-1] >= float(self.params.get("short_rsi", 68)) and regime.name in {"RANGE_LOW_VOL", "RANGE_NORMAL"}:
            return self.signal(symbol, "SHORT", last.close, "Bollinger upper band mean reversion", {"score": 70, "target": middle[-1]})
        return None

    def _template_bb_ride(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        _, upper, lower, width = bollinger(values, 20, 2.0)
        rsi = rsi_values(candles_5m)
        last = candles_5m[-1]
        expanding = width[-1] > width[-2] * float(self.params.get("expand", 1.03))
        if expanding and last.close > upper[-1] and 55 <= rsi[-1] <= 75:
            return self.signal(symbol, "LONG", last.close, "Bollinger band ride breakout", {"score": 75})
        if expanding and last.close < lower[-1] and 25 <= rsi[-1] <= 45:
            return self.signal(symbol, "SHORT", last.close, "Bollinger band ride breakdown", {"score": 75})
        return None

    def _template_vwap_reclaim(self, symbol, candles_5m, candles_15m, regime):
        vwap = rolling_vwap(candles_5m, int(self.params.get("period", 96)))
        values = closes(candles_5m)
        fast, slow = ema(values, 9), ema(values, 21)
        rsi = rsi_values(candles_5m)
        last = candles_5m[-1]
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        if values[-2] <= vwap[-2] < values[-1] and fast[-1] > slow[-1] and rsi[-1] > 50 and vol >= float(self.params.get("volume", 1.2)):
            return self.signal(symbol, "LONG", last.close, "VWAP reclaim with EMA stack", {"score": 74 + vol})
        if values[-2] >= vwap[-2] > values[-1] and fast[-1] < slow[-1] and rsi[-1] < 50 and vol >= float(self.params.get("volume", 1.2)):
            return self.signal(symbol, "SHORT", last.close, "VWAP loss with EMA stack", {"score": 74 + vol})
        return None

    def _template_donchian_breakout(self, symbol, candles_5m, candles_15m, regime):
        lookback = int(self.params.get("lookback", 24))
        prior = candles_5m[-lookback - 1 : -1]
        last = candles_5m[-1]
        trend_values = closes(candles_15m)
        trend_fast, trend_slow = ema(trend_values, 20), ema(trend_values, 50)
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        if not prior or vol < float(self.params.get("volume", 1.25)):
            return None
        if last.close > max(item.high for item in prior) and trend_fast[-1] > trend_slow[-1]:
            return self.signal(symbol, "LONG", last.close, "Donchian high breakout", {"score": 77 + vol})
        if last.close < min(item.low for item in prior) and trend_fast[-1] < trend_slow[-1]:
            return self.signal(symbol, "SHORT", last.close, "Donchian low breakdown", {"score": 77 + vol})
        return None

    def _template_squeeze_release(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        _, upper, lower, width = bollinger(values, 20, 2.0)
        _, _, hist = macd(values)
        last = candles_5m[-1]
        recent_width = width[-40:]
        if not recent_width or min(recent_width) <= 0:
            return None
        was_squeezed = width[-2] <= sorted(recent_width)[max(0, int(len(recent_width) * 0.25) - 1)]
        if was_squeezed and width[-1] > width[-2] * 1.08 and last.close > upper[-1] and hist[-1] > 0:
            return self.signal(symbol, "LONG", last.close, "Bollinger squeeze release up", {"score": 80})
        if was_squeezed and width[-1] > width[-2] * 1.08 and last.close < lower[-1] and hist[-1] < 0:
            return self.signal(symbol, "SHORT", last.close, "Bollinger squeeze release down", {"score": 80})
        return None

    def _template_ha_rsi_volume(self, symbol, candles_5m, candles_15m, regime):
        ha_open, ha_close = heikin_ashi(candles_5m)
        rsi = rsi_values(candles_5m)
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        last = candles_5m[-1]
        if ha_close[-2] <= ha_open[-2] and ha_close[-1] > ha_open[-1] and rsi[-2] <= 50 < rsi[-1] and vol >= float(self.params.get("volume", 1.3)):
            return self.signal(symbol, "LONG", last.close, "Heikin Ashi reversal with RSI50 and volume", {"score": 72 + vol})
        if ha_close[-2] >= ha_open[-2] and ha_close[-1] < ha_open[-1] and rsi[-2] >= 50 > rsi[-1] and vol >= float(self.params.get("volume", 1.3)):
            return self.signal(symbol, "SHORT", last.close, "Heikin Ashi reversal with RSI50 and volume", {"score": 72 + vol})
        return None

    def _template_rsi_divergence_proxy(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        rsi = rsi_values(candles_5m)
        last = candles_5m[-1]
        price_low_now = min(values[-5:])
        price_low_prev = min(values[-12:-5])
        price_high_now = max(values[-5:])
        price_high_prev = max(values[-12:-5])
        rsi_low_now = min(rsi[-5:])
        rsi_low_prev = min(rsi[-12:-5])
        rsi_high_now = max(rsi[-5:])
        rsi_high_prev = max(rsi[-12:-5])
        if price_low_now < price_low_prev and rsi_low_now > rsi_low_prev and rsi[-1] > rsi[-2]:
            return self.signal(symbol, "LONG", last.close, "RSI bullish divergence proxy", {"score": 71})
        if price_high_now > price_high_prev and rsi_high_now < rsi_high_prev and rsi[-1] < rsi[-2]:
            return self.signal(symbol, "SHORT", last.close, "RSI bearish divergence proxy", {"score": 71})
        return None

    def _template_stoch_rsi_proxy(self, symbol, candles_5m, candles_15m, regime):
        values = rsi_values(candles_5m)
        period = int(self.params.get("period", 14))
        if len(values) < period + 3:
            return None
        window = values[-period:]
        low, high = min(window), max(window)
        stoch = 50.0 if high == low else 100.0 * (values[-1] - low) / (high - low)
        prev_window = values[-period - 1 : -1]
        prev_low, prev_high = min(prev_window), max(prev_window)
        prev = 50.0 if prev_high == prev_low else 100.0 * (values[-2] - prev_low) / (prev_high - prev_low)
        last = candles_5m[-1]
        if prev <= 20 < stoch and regime.bias != "SHORT":
            return self.signal(symbol, "LONG", last.close, "StochRSI bullish cross proxy", {"score": 69})
        if prev >= 80 > stoch and regime.bias != "LONG":
            return self.signal(symbol, "SHORT", last.close, "StochRSI bearish cross proxy", {"score": 69})
        return None

    def _template_supertrend_flip(self, symbol, candles_5m, candles_15m, regime):
        direction = supertrend_direction(
            candles_5m,
            int(self.params.get("period", 10)),
            float(self.params.get("multiplier", 3.0)),
        )
        last = candles_5m[-1]
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        if direction[-2] <= 0 < direction[-1] and regime.bias != "SHORT" and vol >= float(self.params.get("volume", 1.0)):
            return self.signal(symbol, "LONG", last.close, "Supertrend bullish flip", {"score": 76 + vol})
        if direction[-2] >= 0 > direction[-1] and regime.bias != "LONG" and vol >= float(self.params.get("volume", 1.0)):
            return self.signal(symbol, "SHORT", last.close, "Supertrend bearish flip", {"score": 76 + vol})
        return None

    def _template_aroon_zscore(self, symbol, candles_5m, candles_15m, regime):
        values = closes(candles_5m)
        period = int(self.params.get("period", 25))
        zperiod = int(self.params.get("zperiod", 50))
        if len(values) < max(period, zperiod) + 2:
            return None
        up, down = aroon(values, period)
        z = zscore(values, zperiod)
        last = candles_5m[-1]
        vol = volume_ratio([item.volume for item in candles_5m], 20)[-1]
        if up[-2] <= down[-2] and up[-1] > down[-1] and -0.5 <= z[-1] <= 2.0 and regime.bias != "SHORT" and vol >= float(self.params.get("volume", 1.0)):
            return self.signal(symbol, "LONG", last.close, "Aroon bullish cross with zscore filter", {"score": 72 + vol})
        if up[-2] >= down[-2] and up[-1] < down[-1] and -2.0 <= z[-1] <= 0.5 and regime.bias != "LONG" and vol >= float(self.params.get("volume", 1.0)):
            return self.signal(symbol, "SHORT", last.close, "Aroon bearish cross with zscore filter", {"score": 72 + vol})
        return None


class ChartAdaptiveRouterStrategy(BaseStrategy):
    strategy_id = "S99"
    name = "CHART_ADAPTIVE_ROUTER"
    leverage = 3
    stop_loss_pct = 0.008
    take_profit_pct = 0.015
    minimum_candles = 120

    def __init__(self, catalog: list[CatalogStrategy], config_path: str | Path = "config/router_config.json"):
        self.catalog = catalog
        self.config_path = Path(config_path)
        self.last_decisions: dict[str, dict[str, Any]] = {}

    def evaluate(self, symbol, candles_5m, candles_15m, context=None):
        regime = analyze_regime(candles_5m, candles_15m)
        config = self._load_config()
        allowed = set(config.get("allowed_strategies") or [])
        enforce_allowlist = bool(config.get("enforce_allowlist", False))
        excluded = set(config.get("excluded_strategies") or [])
        symbol_blacklist = set(config.get("symbol_blacklist") or [])
        minimum_score = float(config.get("minimum_score", 70))
        if symbol in symbol_blacklist:
            self._remember(symbol, regime, "SYMBOL_BLOCKED", None, [])
            return None
        candidates: list[StrategySignal] = []
        for strategy in self.catalog:
            if enforce_allowlist and strategy.strategy_id not in allowed:
                continue
            if not enforce_allowlist and allowed and strategy.strategy_id not in allowed:
                continue
            if strategy.strategy_id in excluded:
                continue
            signal = strategy.evaluate(symbol, candles_5m, candles_15m, context or {})
            if signal is None:
                continue
            if float(signal.metadata.get("score", 0.0)) >= minimum_score:
                candidates.append(signal)
        if not candidates:
            self._remember(symbol, regime, "NO_MATCH", None, [])
            return None
        candidates.sort(key=lambda item: (float(item.metadata.get("score", 0.0)), item.strategy_id), reverse=True)
        selected = candidates[0]
        self._remember(symbol, regime, "SELECTED", selected, candidates[:5])
        return selected

    def should_exit(self, position, candles_5m, candles_15m, context=None):
        return None

    def snapshot(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.name,
            "decisions": self.last_decisions,
        }

    def _remember(self, symbol: str, regime: ChartRegime, outcome: str, selected, candidates) -> None:
        self.last_decisions[symbol] = {
            "regime": regime.name,
            "bias": regime.bias,
            "trend": regime.trend,
            "volatility": regime.volatility,
            "volume": regime.volume,
            "score": round(regime.score, 3),
            "tags": list(regime.tags),
            "outcome": outcome,
            "selected_strategy": selected.strategy_id if selected else None,
            "selected_name": selected.strategy_name if selected else None,
            "candidate_count": len(candidates),
            "top_candidates": [
                {
                    "strategy_id": item.strategy_id,
                    "name": item.strategy_name,
                    "direction": item.direction,
                    "score": round(float(item.metadata.get("score", 0.0)), 3),
                }
                for item in candidates
            ],
        }

    def _load_config(self) -> dict:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}


def analyze_regime(candles_5m, candles_15m) -> ChartRegime:
    values = closes(candles_5m)
    higher = closes(candles_15m)
    ema20, ema50, ema200 = ema(values, 20), ema(values, 50), ema(values, 200)
    higher20, higher50 = ema(higher, 20), ema(higher, 50)
    adx_values = adx(candles_5m, 14)
    atr_values = atr(candles_5m, 14)
    rsi = rsi_values(candles_5m)
    volumes = volume_ratio([item.volume for item in candles_5m], 20)
    _, _, _, widths = bollinger(values, 20, 2.0)
    atr_pct = atr_values[-1] / values[-1] if values[-1] else 0.0
    recent_widths = widths[-80:] or [widths[-1]]
    width_rank = sum(1 for item in recent_widths if item <= widths[-1]) / len(recent_widths)
    trend = "UP" if ema20[-1] > ema50[-1] > ema200[-1] and higher20[-1] > higher50[-1] else "DOWN" if ema20[-1] < ema50[-1] < ema200[-1] and higher20[-1] < higher50[-1] else "MIXED"
    volatility = "HIGH" if atr_pct > 0.018 else "LOW" if atr_pct < 0.006 else "NORMAL"
    volume = "SURGE" if volumes[-1] >= 1.5 else "NORMAL" if volumes[-1] >= 0.8 else "DRY"
    tags = []
    if adx_values[-1] >= 25:
        tags.append("ADX_STRONG")
    if width_rank <= 0.25:
        tags.append("SQUEEZE")
    if width_rank >= 0.75:
        tags.append("EXPANSION")
    if volumes[-1] >= 1.5:
        tags.append("VOLUME_SURGE")
    if rsi[-1] >= 65:
        tags.append("RSI_HOT")
    if rsi[-1] <= 35:
        tags.append("RSI_COLD")

    if trend == "UP" and adx_values[-1] >= 20:
        name, bias = "BULL_TREND", "LONG"
    elif trend == "DOWN" and adx_values[-1] >= 20:
        name, bias = "BEAR_TREND", "SHORT"
    elif width_rank <= 0.25 and volume != "DRY":
        name, bias = "SQUEEZE", "NEUTRAL"
    elif volatility == "HIGH" and adx_values[-1] < 18:
        name, bias = "CHOP_HIGH_VOL", "NEUTRAL"
    elif volatility == "LOW":
        name, bias = "RANGE_LOW_VOL", "NEUTRAL"
    else:
        name, bias = "RANGE_NORMAL", "NEUTRAL"
    score = (
        min(35.0, adx_values[-1])
        + min(20.0, volumes[-1] * 10.0)
        + (15.0 if trend != "MIXED" else 5.0)
        + (10.0 if "SQUEEZE" in tags or "EXPANSION" in tags else 5.0)
    )
    return ChartRegime(name, bias, trend, volatility, volume, score, tuple(tags))


def supertrend_direction(candles, period: int = 10, multiplier: float = 3.0) -> list[int]:
    atr_values = atr(candles, period)
    upper: list[float] = []
    lower: list[float] = []
    direction = [1] * len(candles)
    final_upper = 0.0
    final_lower = 0.0
    for index, candle in enumerate(candles):
        hl2 = (candle.high + candle.low) / 2.0
        basic_upper = hl2 + multiplier * atr_values[index]
        basic_lower = hl2 - multiplier * atr_values[index]
        if index == 0:
            final_upper, final_lower = basic_upper, basic_lower
        else:
            previous = candles[index - 1]
            final_upper = basic_upper if basic_upper < final_upper or previous.close > final_upper else final_upper
            final_lower = basic_lower if basic_lower > final_lower or previous.close < final_lower else final_lower
            if candle.close > final_upper:
                direction[index] = 1
            elif candle.close < final_lower:
                direction[index] = -1
            else:
                direction[index] = direction[index - 1]
        upper.append(final_upper)
        lower.append(final_lower)
    return direction


def aroon(values: list[float], period: int) -> tuple[list[float], list[float]]:
    up, down = [50.0] * len(values), [50.0] * len(values)
    for index in range(period, len(values)):
        window = values[index - period + 1 : index + 1]
        high_index = max(range(len(window)), key=lambda item: window[item])
        low_index = min(range(len(window)), key=lambda item: window[item])
        up[index] = 100.0 * high_index / max(1, period - 1)
        down[index] = 100.0 * low_index / max(1, period - 1)
    return up, down


def zscore(values: list[float], period: int) -> list[float]:
    output = [0.0] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        sigma = math.sqrt(variance)
        output[index] = (values[index] - mean) / sigma if sigma else 0.0
    return output


def build_catalog_strategies() -> list[CatalogStrategy]:
    definitions = [
        ("S20", "EMA9_21_PULLBACK", "ema_pullback", ("BULL_TREND", "BEAR_TREND"), {"fast": 9, "slow": 21, "volume": 1.0}),
        ("S21", "EMA12_26_PULLBACK", "ema_pullback", ("BULL_TREND", "BEAR_TREND"), {"fast": 12, "slow": 26, "volume": 1.05}),
        ("S22", "EMA20_50_PULLBACK", "ema_pullback", ("BULL_TREND", "BEAR_TREND"), {"fast": 20, "slow": 50, "volume": 1.0}),
        ("S23", "EMA9_21_VOLUME_BREAKOUT", "ema_breakout", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"lookback": 20, "volume": 1.35}),
        ("S24", "EMA20_50_VOLUME_BREAKOUT", "ema_breakout", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"lookback": 30, "volume": 1.25}),
        ("S25", "MACD_RSI_MOMENTUM", "macd_momentum", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"volume": 1.0}),
        ("S26", "MACD_VOLUME_MOMENTUM", "macd_momentum", ("BULL_TREND", "BEAR_TREND"), {"volume": 1.25}),
        ("S27", "BB_RSI_REVERT_FAST", "bb_mean_revert", ("RANGE_LOW_VOL", "RANGE_NORMAL"), {"long_rsi": 32, "short_rsi": 68}),
        ("S28", "BB_RSI_REVERT_DEEP", "bb_mean_revert", ("RANGE_LOW_VOL", "RANGE_NORMAL"), {"long_rsi": 28, "short_rsi": 72}),
        ("S29", "BB_RIDE_EXPANSION", "bb_ride", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"expand": 1.03}),
        ("S30", "BB_RIDE_STRICT", "bb_ride", ("SQUEEZE",), {"expand": 1.10}),
        ("S31", "VWAP_RECLAIM_MOMENTUM", "vwap_reclaim", ("BULL_TREND", "BEAR_TREND", "RANGE_NORMAL"), {"volume": 1.2}),
        ("S32", "VWAP_RECLAIM_VOLUME", "vwap_reclaim", ("BULL_TREND", "BEAR_TREND"), {"volume": 1.5}),
        ("S33", "DONCHIAN_20_BREAKOUT", "donchian_breakout", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"lookback": 20, "volume": 1.25}),
        ("S34", "DONCHIAN_30_BREAKOUT", "donchian_breakout", ("BULL_TREND", "BEAR_TREND"), {"lookback": 30, "volume": 1.15}),
        ("S35", "SQUEEZE_RELEASE_FAST", "squeeze_release", ("SQUEEZE",), {}),
        ("S36", "SQUEEZE_RELEASE_TREND", "squeeze_release", ("SQUEEZE", "BULL_TREND", "BEAR_TREND"), {}),
        ("S37", "HA_RSI_VOLUME_REVERSAL", "ha_rsi_volume", ("RANGE_NORMAL", "BULL_TREND", "BEAR_TREND"), {"volume": 1.3}),
        ("S38", "HA_RSI_VOLUME_STRICT", "ha_rsi_volume", ("BULL_TREND", "BEAR_TREND"), {"volume": 1.6}),
        ("S39", "RSI_DIVERGENCE_PROXY", "rsi_divergence_proxy", ("RANGE_NORMAL", "RANGE_LOW_VOL"), {}),
        ("S40", "RSI_DIVERGENCE_TREND", "rsi_divergence_proxy", ("BULL_TREND", "BEAR_TREND"), {}),
        ("S41", "STOCH_RSI_RANGE", "stoch_rsi_proxy", ("RANGE_LOW_VOL", "RANGE_NORMAL"), {"period": 14}),
        ("S42", "STOCH_RSI_TREND", "stoch_rsi_proxy", ("BULL_TREND", "BEAR_TREND"), {"period": 14}),
        ("S43", "EMA_SCALP_5_13", "ema_pullback", ("BULL_TREND", "BEAR_TREND"), {"fast": 5, "slow": 13, "volume": 1.05}),
        ("S44", "EMA_SCALP_8_21", "ema_breakout", ("BULL_TREND", "BEAR_TREND"), {"fast": 8, "slow": 21, "lookback": 12, "volume": 1.2}),
        ("S45", "MACD_SQUEEZE_CONFIRM", "macd_momentum", ("SQUEEZE",), {"volume": 1.1}),
        ("S46", "VWAP_RANGE_SNAP", "vwap_reclaim", ("RANGE_NORMAL",), {"volume": 1.1}),
        ("S47", "DONCHIAN_VOLATILITY_BREAK", "donchian_breakout", ("SQUEEZE", "BULL_TREND", "BEAR_TREND"), {"lookback": 40, "volume": 1.4}),
        ("S48", "BB_MEAN_REVERT_LIGHT", "bb_mean_revert", ("RANGE_LOW_VOL",), {"long_rsi": 35, "short_rsi": 65}),
        ("S49", "BB_MEAN_REVERT_STRICT", "bb_mean_revert", ("RANGE_LOW_VOL",), {"long_rsi": 25, "short_rsi": 75}),
        ("S50", "EMA_MACRO_PULLBACK", "ema_pullback", ("BULL_TREND", "BEAR_TREND"), {"fast": 21, "slow": 55, "macro": 89, "volume": 1.0}),
        ("S51", "EMA_VOLUME_COMPRESSION_BREAK", "ema_breakout", ("SQUEEZE",), {"lookback": 18, "volume": 1.6}),
        ("S52", "HA_TREND_CONTINUATION", "ha_rsi_volume", ("BULL_TREND", "BEAR_TREND"), {"volume": 1.1}),
        ("S53", "MACD_LOW_VOL_EXPANSION", "macd_momentum", ("RANGE_LOW_VOL", "SQUEEZE"), {"volume": 1.15}),
        ("S54", "VWAP_TREND_REENTRY", "vwap_reclaim", ("BULL_TREND", "BEAR_TREND"), {"period": 48, "volume": 1.25}),
        ("S55", "DONCHIAN_TREND_FAST", "donchian_breakout", ("BULL_TREND", "BEAR_TREND"), {"lookback": 14, "volume": 1.3}),
        ("S56", "SUPER_TREND_10_3", "supertrend_flip", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"period": 10, "multiplier": 3.0, "volume": 1.0}),
        ("S57", "SUPER_TREND_8_2", "supertrend_flip", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"period": 8, "multiplier": 2.0, "volume": 1.1}),
        ("S58", "SUPER_TREND_14_3", "supertrend_flip", ("BULL_TREND", "BEAR_TREND"), {"period": 14, "multiplier": 3.0, "volume": 1.0}),
        ("S59", "AROON_ZSCORE_25", "aroon_zscore", ("BULL_TREND", "BEAR_TREND", "RANGE_NORMAL"), {"period": 25, "zperiod": 50, "volume": 1.0}),
        ("S60", "AROON_ZSCORE_14", "aroon_zscore", ("BULL_TREND", "BEAR_TREND", "SQUEEZE"), {"period": 14, "zperiod": 40, "volume": 1.15}),
    ]
    return [
        CatalogStrategy(strategy_id, name, template, regimes, params=params, source="github_reddit_common")
        for strategy_id, name, template, regimes, params in definitions
    ]
