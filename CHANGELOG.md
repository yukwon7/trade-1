# CHANGELOG

## 2026-06-28

- [AUTONOMOUS] Server B was carrying analysis commands -> split execution-only Telegram bot from analysis Telegram bot.
- [AUTONOMOUS] Server B needed safe hot reload -> added validated config reloader that rejects invalid JSON and keeps previous valid config.
- [AUTONOMOUS] Deployment needed rollback path -> added config-only deploy and rollback scripts with remote backups.
- [AUTONOMOUS] Hermes must not trade directly -> added Server A Hermes cycle that only writes config/report JSON.
- [AUTONOMOUS] Existing open positions must be preserved -> runtime risk updates affect only new entries and position management remains unchanged.
- [AUTONOMOUS] User requested AI orchestrator -> added optional Server-A-only AI suggestion layer with rule/gate fallback and risk clamps.
- [AUTONOMOUS] User provided a second Telegram bot token -> added Server-A analysis bot token support via TELEGRAM_ANALYSIS_BOT_TOKEN without writing secrets to code.
