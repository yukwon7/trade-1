"""Dry-run research candidates for increasing signal frequency."""

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy
from FReinforcedStrategy import FReinforcedStrategy


class _FrequencyBreakoutBase(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 220

    minimal_roi = {"0": 0.16}
    stoploss = -0.08
    trailing_stop = True
    trailing_stop_positive = 0.04
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = False

    breakout_period = 12
    adx_threshold = 18

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["breakout_high"] = (
            dataframe["high"].rolling(self.breakout_period).max().shift(1)
        )
        dataframe["breakout_low"] = (
            dataframe["low"].rolling(self.breakout_period).min().shift(1)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["breakout_high"])
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["adx"] > self.adx_threshold)
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        dataframe.loc[
            (dataframe["close"] < dataframe["breakout_low"])
            & (dataframe["close"] < dataframe["ema_200"])
            & (dataframe["adx"] > self.adx_threshold)
            & (dataframe["volume"] > 0),
            "enter_short",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

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


class Frequency20ADX20(_FrequencyBreakoutBase):
    breakout_period = 20
    adx_threshold = 20


class Frequency12ADX18(_FrequencyBreakoutBase):
    breakout_period = 12
    adx_threshold = 18


class Frequency8ADX18(_FrequencyBreakoutBase):
    breakout_period = 8
    adx_threshold = 18


class Frequency8ADX15(_FrequencyBreakoutBase):
    breakout_period = 8
    adx_threshold = 15


class FReinforced20(FReinforcedStrategy):
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
