# Source: https://github.com/freqtrade/freqtrade-strategies
# Commit: dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4
# License: GPL-3.0

from functools import reduce

import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter


class FAdxSmaStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    minimal_roi = {"60": 0.075, "30": 0.1, "0": 0.05}
    stoploss = -0.05
    can_short = True
    trailing_stop = False
    process_only_new_candles = True
    startup_candle_count: int = 14

    pos_entry_adx = DecimalParameter(15, 40, decimals=1, default=30.0, space="buy")
    pos_exit_adx = DecimalParameter(15, 40, decimals=1, default=30.0, space="sell")
    adx_period = IntParameter(4, 24, default=14, space="buy")
    sma_short_period = IntParameter(4, 24, default=12, space="buy")
    sma_long_period = IntParameter(12, 175, default=48, space="buy")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.adx_period.range:
            dataframe[f"adx_{val}"] = ta.ADX(dataframe, timeperiod=val)
        for val in self.sma_short_period.range:
            dataframe[f"sma_short_{val}"] = ta.SMA(dataframe, timeperiod=val)
        for val in self.sma_long_period.range:
            dataframe[f"sma_long_{val}"] = ta.SMA(dataframe, timeperiod=val)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions_long = [
            dataframe[f"adx_{self.adx_period.value}"] > self.pos_entry_adx.value,
            qtpylib.crossed_above(
                dataframe[f"sma_short_{self.sma_short_period.value}"],
                dataframe[f"sma_long_{self.sma_long_period.value}"],
            ),
        ]
        conditions_short = [
            dataframe[f"adx_{self.adx_period.value}"] > self.pos_entry_adx.value,
            qtpylib.crossed_below(
                dataframe[f"sma_short_{self.sma_short_period.value}"],
                dataframe[f"sma_long_{self.sma_long_period.value}"],
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
