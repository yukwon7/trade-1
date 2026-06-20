# Source: https://github.com/freqtrade/freqtrade-strategies
# Commit: dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4
# License: GPL-3.0
# Modified 2026-06-19: added explicit parameter spaces required by Freqtrade 2026.5.1.

from datetime import datetime
from functools import reduce
from typing import Any

import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from pandas import DataFrame
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter
from technical.util import resample_to_interval, resampled_merge

try:
    from trade_learning import infer_source, record_entry_decision, should_block_signal
except Exception:
    infer_source = None
    record_entry_decision = None
    should_block_signal = None


class FReinforcedStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    minimal_roi = {"60": 0.075, "30": 0.1, "0": 0.05}
    stoploss = -0.05
    can_short = True
    trailing_stop = False
    process_only_new_candles = True
    # 50 one-hour SMA values require at least 600 five-minute candles.
    startup_candle_count: int = 720

    pos_entry_adx = DecimalParameter(15, 40, decimals=1, default=30.0, space="buy")
    pos_exit_adx = DecimalParameter(15, 40, decimals=1, default=30.0, space="sell")
    adx_period = IntParameter(4, 24, default=14, space="buy")
    ema_short_period = IntParameter(4, 24, default=8, space="buy")
    ema_long_period = IntParameter(12, 175, default=21, space="buy")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.adx_period.range:
            dataframe[f"adx_{val}"] = ta.ADX(dataframe, timeperiod=val)
        for val in self.ema_short_period.range:
            dataframe[f"ema_short_{val}"] = ta.EMA(dataframe, timeperiod=val)
        for val in self.ema_long_period.range:
            dataframe[f"ema_long_{val}"] = ta.EMA(dataframe, timeperiod=val)

        bollinger = qtpylib.bollinger_bands(dataframe["close"], window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_upperband"] = bollinger["upper"]
        dataframe["bb_middleband"] = bollinger["mid"]

        self.resample_interval = timeframe_to_minutes(self.timeframe) * 12
        dataframe_long = resample_to_interval(dataframe, self.resample_interval)
        dataframe_long["sma"] = ta.SMA(dataframe_long, timeperiod=50, price="close")
        return resampled_merge(dataframe, dataframe_long, fill_na=True)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions_long = [
            dataframe["close"] > dataframe[f"resample_{self.resample_interval}_sma"],
            qtpylib.crossed_above(
                dataframe[f"ema_short_{self.ema_short_period.value}"],
                dataframe[f"ema_long_{self.ema_long_period.value}"],
            ),
        ]
        conditions_short = [
            dataframe["close"] < dataframe[f"resample_{self.resample_interval}_sma"],
            qtpylib.crossed_below(
                dataframe[f"ema_short_{self.ema_short_period.value}"],
                dataframe[f"ema_long_{self.ema_long_period.value}"],
            ),
        ]
        dataframe.loc[reduce(lambda x, y: x & y, conditions_long), "enter_long"] = 1
        dataframe.loc[reduce(lambda x, y: x & y, conditions_short), "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions_close = [
            dataframe[f"adx_{self.adx_period.value}"] < self.pos_entry_adx.value
        ]
        close_signal = reduce(lambda x, y: x & y, conditions_close)
        dataframe.loc[close_signal, "exit_long"] = 1
        dataframe.loc[close_signal, "exit_short"] = 1
        return dataframe


class FReinforced20Strategy(FReinforcedStrategy):
    """Active dry-run variant with frequent entries and bounded loss exits."""

    entry_adx_threshold = 20.0
    stoploss = -0.08

    @property
    def protections(self):
        return [{"method": "CooldownPeriod", "stop_duration_candles": 12}]

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_short = dataframe[f"ema_short_{self.ema_short_period.value}"]
        ema_long = dataframe[f"ema_long_{self.ema_long_period.value}"]
        hourly_sma = dataframe[f"resample_{self.resample_interval}_sma"]
        adx = dataframe[f"adx_{self.adx_period.value}"]

        dataframe.loc[
            (dataframe["close"] > hourly_sma)
            & (ema_short > ema_long)
            & (adx > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_adx20_long")
        dataframe.loc[
            (dataframe["close"] < hourly_sma)
            & (ema_short < ema_long)
            & (adx > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "trend_adx20_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_short = dataframe[f"ema_short_{self.ema_short_period.value}"]
        ema_long = dataframe[f"ema_long_{self.ema_long_period.value}"]
        bull_cross = qtpylib.crossed_above(ema_short, ema_long)
        bear_cross = qtpylib.crossed_below(ema_short, ema_long)
        low_adx = dataframe[f"adx_{self.adx_period.value}"] < self.entry_adx_threshold
        dataframe.loc[
            ((ema_short < ema_long) | (low_adx & ~bull_cross))
            & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_or_adx_exit")
        dataframe.loc[
            ((ema_short > ema_long) | (low_adx & ~bear_cross))
            & (dataframe["volume"] > 0),
            ["exit_short", "exit_tag"],
        ] = (1, "trend_or_adx_exit")
        return dataframe

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        current_profit = trade.calc_profit_ratio(rate)
        if exit_reason == "exit_signal" and -0.05 < current_profit < 0:
            return False
        return True

    def _learning_snapshot(self, pair: str) -> tuple[dict[str, Any], dict[str, Any]]:
        indicators: dict[str, Any] = {}
        conditions: dict[str, Any] = {}
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                return indicators, conditions

            last = dataframe.iloc[-1]
            ema_short_col = f"ema_short_{self.ema_short_period.value}"
            ema_long_col = f"ema_long_{self.ema_long_period.value}"
            adx_col = f"adx_{self.adx_period.value}"
            hourly_sma_col = f"resample_{self.resample_interval}_sma"

            close = float(last.get("close", 0))
            ema_short = float(last.get(ema_short_col, 0))
            ema_long = float(last.get(ema_long_col, 0))
            adx = float(last.get(adx_col, 0))
            hourly_sma = float(last.get(hourly_sma_col, 0))
            volume = float(last.get("volume", 0))

            indicators = {
                "close": close,
                "ema_short": ema_short,
                "ema_long": ema_long,
                "hourly_sma": hourly_sma,
                "adx": adx,
                "volume": volume,
                "entry_adx_threshold": float(self.entry_adx_threshold),
            }
            conditions = {
                "price_above_hourly_sma": close > hourly_sma,
                "price_below_hourly_sma": close < hourly_sma,
                "ema_short_above_ema_long": ema_short > ema_long,
                "ema_short_below_ema_long": ema_short < ema_long,
                "adx_above_threshold": adx > float(self.entry_adx_threshold),
                "has_volume": volume > 0,
            }
        except Exception:
            return indicators, conditions
        return indicators, conditions

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        source = infer_source(entry_tag) if infer_source else "auto"
        blocked = False
        blocked_reason = None

        if source == "auto" and should_block_signal:
            try:
                blocked, blocked_reason = should_block_signal(pair, side, entry_tag)
            except Exception:
                blocked = False
                blocked_reason = None

        indicators, conditions = self._learning_snapshot(pair)
        if record_entry_decision:
            try:
                record_entry_decision(
                    pair=pair,
                    side=side,
                    enter_tag=entry_tag,
                    strategy=self.__class__.__name__,
                    source=source,
                    allowed=not blocked,
                    blocked_reason=blocked_reason,
                    rate=rate,
                    amount=amount,
                    leverage=kwargs.get("leverage"),
                    indicators=indicators,
                    conditions=conditions,
                )
            except Exception:
                pass

        return not blocked

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return min(20.0, max_leverage)
