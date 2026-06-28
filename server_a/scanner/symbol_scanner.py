from __future__ import annotations

from datetime import datetime, timezone


def select_symbols_from_tickers(tickers: list[dict], limit: int = 10) -> dict:
    usdt = []
    for ticker in tickers:
        symbol = str(ticker.get("symbol", "")).upper()
        if not symbol.endswith("USDT"):
            continue
        try:
            quote_volume = float(ticker.get("quoteVolume") or 0.0)
        except (TypeError, ValueError):
            quote_volume = 0.0
        usdt.append((symbol, quote_volume))
    selected = [symbol for symbol, _ in sorted(usdt, key=lambda item: item[1], reverse=True)[:limit]]
    return {
        "symbols": selected,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "server_a_scanner_24h_quote_volume",
    }
