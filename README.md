# trade-1 chart router

Binance USDT-M futures paper trading bot. The active runtime is the chart-adaptive router:

- `S99` analyzes each symbol's chart regime.
- `S20` through `S55` are the only active strategy catalog entries.
- The router selects a matching strategy only when the chart condition and strategy signal both agree.
- Live readiness is blocked until `analytics.stress_tester` passes the router-only stress criteria.

This repository is paper trading only. Secrets stay in `.env`; API keys are not hardcoded.

## Runtime

Server 1 runs paper trading:

```bash
scripts/run_paper.sh
```

Server 2 runs analysis and pushes runtime config to Server 1:

```bash
scripts/run_analysis.sh
```

Analysis writes:

- `config/router_config.json`
- `config/stress_test_report.json`

Paper runtime writes:

- `config/router_control.json`
- `config/router_snapshot.json`

These files are runtime state and are intentionally ignored by Git.

## Telegram

Current commands:

- `/status`: bot status, balance, open positions
- `/router`: latest router cycle and selected strategies
- `/regime`: chart regime for all symbols
- `/regime BTCUSDT`: chart regime and candidate strategies for one symbol
- `/strategy`: current strategy
- `/strategy S99`: use chart router
- `/strategy S20` through `/strategy S55`: manually force one catalog strategy
- `/strategy auto`: return to automatic router
- `/strategies`: catalog summary
- `/stress`: live-readiness stress test
- `/positions`: open positions
- `/balance`: paper account balance
- `/trades`: recent completed trades
- `/daily`, `/weekly`, `/monthly`: period performance
- `/pause`, `/resume`: pause or resume new entries

## Strategy Families

The active catalog contains 36 local strategy variants:

- EMA trend pullback and breakout
- MACD histogram momentum
- Bollinger mean reversion and band ride
- VWAP reclaim/loss
- Donchian breakout
- Bollinger squeeze release
- Heikin Ashi plus RSI and volume
- RSI divergence proxy
- StochRSI proxy

Public GitHub/Reddit materials are used only as idea references. Public popularity is not treated as profitability proof. See `docs/strategy_router_sources.md`.

## Risk

Hard-coded runtime safety defaults:

- Max leverage: `3x`
- Max open positions: `3`
- Risk per trade: `1%`
- Paper trading only

`/stress` must report `live_ready: True` before any real-trading discussion.
