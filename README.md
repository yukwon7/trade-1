# trade-1 two-server trading system

Binance USDT-M futures paper trading bot split into:

- Server A: analysis / Hermes / backtest / stress test / config generation.
- Server B: lightweight execution only.

Server B must not run heavy analysis, strategy tournaments, scanners, or AI calls. It reads validated config files and manages positions.

The execution runtime uses:

- `S99` analyzes each symbol's chart regime.
- `S20` through `S60` are the only active strategy catalog entries.
- The router selects a matching strategy only when the chart condition and strategy signal both agree.
- Live readiness is blocked until `analytics.stress_tester` passes the router-only stress criteria.

This repository is paper trading only. Secrets stay in `.env`; API keys are not hardcoded.

## Runtime

Server B runs lightweight execution:

```bash
scripts/run_paper.sh
```

Server A runs Hermes analysis:

```bash
scripts/run_analysis_cycle.sh
```

Optional AI orchestration is Server-A-only. If no AI key is configured, Hermes runs deterministic rules only.

Supported `.env` variables:

```bash
HERMES_AI_PROVIDER=deepseek   # or openai
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-chat
# or
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
```

Server B never imports or calls the AI client.

Analysis writes:

- `config/strategy_config.json`
- `config/risk_config.json`
- `config/selected_symbols.json`
- `data/router_backtest_stress_period.json`
- `config/stress_test_report.json`
- `config/strategy_decision_report.json`

Execution runtime writes:

- `config/execution_health.json`
- `config/paper_state.json`

These files are runtime state and are intentionally ignored by Git.

## Config-only Server B deploy

From Server A:

```bash
scripts/deploy_server_b_config_only.sh
```

Rollback:

```bash
scripts/rollback_server_b_config.sh latest
```

Never sync `.env`. Server B hot-reloads config on the next execution cycle.

## Telegram

Server B execution commands:

- `/status`: bot status, balance, open positions
- `/positions`: open positions
- `/risk`: active risk config
- `/pause`, `/resume`: pause or resume new entries
- `/close_all CONFIRM`: emergency close all current paper positions
- `/config`: active config and validation errors
- `/health`: execution health snapshot

Server A analysis commands:

- `/analyze`, `/daily`, `/weekly`, `/monthly`
- `/stress`, `/backtest`
- `/strategies`, `/decision`
- `/deploy_config`, `/rollback_config`, `/hermes_status`

## Stress-period router approval

Server 2 can approve the runtime strategy allowlist from the paper-trading stress period already stored in `trades.db`:

```bash
scripts/run_router_backtest.sh
```

The default `ROUTER_BACKTEST_DAYS=0` infers the actual DB period instead of using a fixed one-year window. The generated `config/router_config.json` sets `enforce_allowlist=true`, so Server 1 evaluates only approved profitable strategies on the next cycle without a process restart.

## Strategy Families

The active catalog contains 41 local strategy variants:

- EMA trend pullback and breakout
- MACD histogram momentum
- Bollinger mean reversion and band ride
- VWAP reclaim/loss
- Donchian breakout
- Bollinger squeeze release
- Heikin Ashi plus RSI and volume
- RSI divergence proxy
- StochRSI proxy
- Supertrend variants
- Aroon plus ZScore filters

Public GitHub/Reddit materials are used only as idea references. Public popularity is not treated as profitability proof. See `docs/strategy_router_sources.md`.

## Risk

Hard-coded runtime safety defaults:

- Max leverage: `3x`
- Max open positions: `3`
- Risk per trade: `1%`
- Paper trading only

`/stress` must report `live_ready: True` before any real-trading discussion.
