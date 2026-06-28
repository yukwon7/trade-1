from __future__ import annotations

from strategies.market_router import ChartAdaptiveRouterStrategy, build_catalog_strategies


CATALOG_STRATEGIES = build_catalog_strategies()

STRATEGIES = {
    **{strategy.strategy_id: strategy for strategy in CATALOG_STRATEGIES},
}

STRATEGIES["S99"] = ChartAdaptiveRouterStrategy(CATALOG_STRATEGIES)

STRATEGY_ROTATION_IDS = ("S99",)


def get_strategy(strategy_id: str):
    return STRATEGIES.get(strategy_id.upper())
