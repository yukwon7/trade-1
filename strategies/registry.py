from __future__ import annotations

from strategies.market_router import ChartAdaptiveRouterStrategy, build_catalog_strategies


CATALOG_STRATEGIES = build_catalog_strategies()

STRATEGIES = {
    **{strategy.strategy_id: strategy for strategy in CATALOG_STRATEGIES},
}

STRATEGIES["S99"] = ChartAdaptiveRouterStrategy(CATALOG_STRATEGIES)

STRATEGY_ALIASES = {
    "CHART_ADAPTIVE_ROUTER": "S99",
    "MACD_RSI_MOMENTUM": "S25",
    "EMA_VWAP_MOMENTUM": "S54",
    "BREAKOUT_VOLUME": "S24",
    "MEAN_REVERSION_BB": "S27",
}

STRATEGY_ROTATION_IDS = ("S99",)


def normalize_strategy_id(strategy_id: str) -> str:
    value = strategy_id.upper()
    return STRATEGY_ALIASES.get(value, value)


def get_strategy(strategy_id: str):
    return STRATEGIES.get(normalize_strategy_id(strategy_id))
