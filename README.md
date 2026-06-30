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
The Telegram analysis bot can also run as the Hermes AI Orchestrator room.

Supported `.env` variables:

```bash
HERMES_AI_PROVIDER=nvidia
GLM_API_KEY=...
GLM_MODEL=glm-4-flash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=qwen/qwen3-235b-a22b:free
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-chat
XAI_API_KEY=...
GROK_MODEL=grok-3-mini
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
NVIDIA_API_KEY=...
NVIDIA_MODEL=openai/gpt-oss-120b,z-ai/glm-5.1,qwen/qwen3.5-397b-a17b,deepseek-ai/deepseek-v4-pro
# comma-separated fallback models are also supported:
# NVIDIA_MODEL=deepseek-ai/deepseek-r1,meta/llama-3.1-70b-instruct
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
# Optional per-model NVIDIA keys. Keep real values in .env only.
NVIDIA_MODEL_API_KEY_OPENAI_GPT_OSS_120B=...
NVIDIA_MODEL_API_KEY_Z_AI_GLM_5_1=...
NVIDIA_MODEL_API_KEY_QWEN_QWEN3_5_397B_A17B=...
NVIDIA_MODEL_API_KEY_DEEPSEEK_AI_DEEPSEEK_V4_PRO=...
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

Server A Hermes AI Orchestrator commands:

- `/task <goal>`: start a development task; Hermes assigns agents and returns a consensus pending approval
- `/goal <goal>`: set a persistent Hermes goal; the bot reports progress back to Telegram until the orchestration cycle completes
- `/progress`: show current goal progress
- `/codex <task>`: enqueue a hard task for Codex processing
- `/codex_status [id]`: inspect the Codex task queue
- `/exec_status`: show whether Node/npm/Codex CLI are installed on Server A
- `/server_status`: run safe read-only server status checks
- `/run_tests`: run the project unit test suite on Server A
- `/logs [service]`: show recent allowlisted Hermes service logs
- `/codex_run`: execute the next queued Codex task when `HERMES_CODEX_DIRECT_RUN=true` and Codex CLI authentication is ready
- `/debate <topic>`: summon the full agent team for a structured debate
- `/review <code>`: ARES-led code review with implementation and optimization input
- `/approve`: approve the pending consensus for follow-up execution by the Codex/operator workflow
- `/reject <reason>`: reject the pending consensus and request rework
- `/status`: current pending task, model status, and process-local usage
- `/agents`: HERMES, ZEUS, ATHENA, APOLLO, ARES, HEPHAESTUS, ORACLE roles and assigned NVIDIA models
- `/stop`: stop the current pending work/goal and clear cache
- `/bind_agent_room`: authorize the current Telegram room
- hidden operator/debug commands still exist: `/model`, `/cost`, `/think`, `/free`, `/gpt`, `/nvidia`, `/code`, `/analyze`, `/stress`, `/backtest`, `/decision`
- plain text messages are routed automatically when `AGENT_CONVERSATION_ENABLED=true`

Hermes uses smart agent selection by default:

- simple implementation tasks use a lean 2-agent team
- medium tasks use a balanced implementation/verification team
- deployment, security, Server B, API-key, or production-impact tasks escalate automatically
- `모든 에이전트`, `전체 토론`, or `/debate` forces full-team discussion
- `HERMES_MAX_AGENTS_PER_TASK` caps non-deep task fan-out to protect tokens and latency

Codex bridge:

- Telegram writes tasks to `config/codex_tasks.json`
- `/goal` only enqueues Codex when the plan is complex, deployment-sensitive, explicitly asks for Codex, or needs final code modification
- simple goals stay with Hermes agents; they draft the answer/plan without spending Codex work
- `scripts/run_codex_worker.sh` processes one queued task when Codex CLI is installed on Server A
- direct execution is disabled unless `HERMES_CODEX_DIRECT_RUN=true`
- Server A must pass `codex doctor`; otherwise `/codex_run` blocks with an authentication-required message
- NVIDIA NIM keys are used by Hermes agents, but current Codex CLI execution should use Codex/OpenAI auth (`codex login` or supported `OPENAI_API_KEY`). A NVIDIA NIM dry-run rejected Codex tool schema in the Responses API.
- default Codex sandbox is `workspace-write`; destructive commands and Server B changes still require external approval
- safe execution commands are allowlisted and execute immediately from Telegram; arbitrary shell is not exposed

Server A can use a separate Telegram bot token:

```bash
TELEGRAM_ANALYSIS_BOT_TOKEN=...
TELEGRAM_ANALYSIS_CHAT_ID=...   # optional; defaults to TELEGRAM_CHAT_ID
```

Run it with:

```bash
scripts/run_analysis_bot.sh
```

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
