# CHANGELOG

## 2026-06-28

- [AUTONOMOUS] Server B was carrying analysis commands -> split execution-only Telegram bot from analysis Telegram bot.
- [AUTONOMOUS] Server B needed safe hot reload -> added validated config reloader that rejects invalid JSON and keeps previous valid config.
- [AUTONOMOUS] Deployment needed rollback path -> added config-only deploy and rollback scripts with remote backups.
- [AUTONOMOUS] Hermes must not trade directly -> added Server A Hermes cycle that only writes config/report JSON.
- [AUTONOMOUS] Existing open positions must be preserved -> runtime risk updates affect only new entries and position management remains unchanged.
- [AUTONOMOUS] User requested AI orchestrator -> added optional Server-A-only AI suggestion layer with rule/gate fallback and risk clamps.
- [AUTONOMOUS] User provided a second Telegram bot token -> added Server-A analysis bot token support via TELEGRAM_ANALYSIS_BOT_TOKEN without writing secrets to code.
- [AUTONOMOUS] 2026-06-29T00:00:00Z | server_a/hermes/env_manager.py,self_tuner.py | allow safe optional .env defaults and runtime tuning | append-only startup defaults plus restricted 6h self-tune loop.
- [AUTONOMOUS] 2026-06-29T00:00:00Z | server_a/hermes/autonomy.py,analysis_bot.py | monitor and commit support for autonomous changes | added monitor notification helper, changelog helper, git auto-commit utility, and hermes.log file logging.
- [AUTONOMOUS] 2026-06-29T00:00:00Z | server_a/hermes/agent_orchestra.py,notify/telegram_analysis_bot.py | second Telegram bot should become AI agent room | added agent chat, dev assistant mode, personas, safe git status and test commands.
- [USER] 2026-06-29T00:00:00Z | notify/telegram_analysis_bot.py | second Telegram room did not recognize chat and old commands remained | added room binding, config-backed allowed chats, direct chat routing, and AI-orchestra-first command menu.
- [USER] 2026-06-29T00:00:00Z | server_a/hermes/agent_router.py,clients/ai_client.py,notify/telegram_analysis_bot.py | Hermes v3 multi-model orchestra requested | added GLM, Gemini, OpenRouter/Qwen, DeepSeek, Grok, OpenAI, NVIDIA provider slots plus Telegram routing commands.
