def calculate_position_size(
    balance: float,
    risk_per_trade: float,
    entry_price: float,
    stop_price: float,
    leverage: int,
    available_margin: float | None = None,
) -> float:
    stop_distance = abs(entry_price - stop_price)
    if balance <= 0 or risk_per_trade <= 0 or stop_distance <= 0 or entry_price <= 0 or leverage <= 0:
        return 0.0
    quantity = balance * risk_per_trade / stop_distance
    margin_limit = balance if available_margin is None else max(0.0, available_margin)
    max_quantity = margin_limit * leverage / entry_price
    return max(0.0, min(quantity, max_quantity))
