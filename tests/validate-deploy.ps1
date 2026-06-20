param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..").Path
$requiredFiles = @(
  'deploy\configure-swap.sh',
  'deploy\install-primary.sh',
  'deploy\install-standby.sh',
  'deploy\preflight.sh',
  'deploy\promote-standby.sh',
  'deploy\backup-to-secondary.sh',
  'deploy\watch-primary.sh',
  'deploy\freqtrade.service',
  'deploy\config.json.template',
  'deploy\backtest.config.json',
  'deploy\benchmark-candidates.sh',
  'deploy\activate-frequent-strategy.sh',
  'deploy\trade_learning.py',
  'deploy\sync_learning.py',
  'deploy\review_learning.py',
  'deploy\recover_journal_trades.py',
  'deploy\trade-learning-sync.service',
  'deploy\trade-learning-sync.timer',
  'deploy\trade-learning-review-daily.service',
  'deploy\trade-learning-review-daily.timer',
  'deploy\trade-learning-review-weekly.service',
  'deploy\trade-learning-review-weekly.timer',
  'deploy\trade-learning-review-monthly.service',
  'deploy\trade-learning-review-monthly.timer',
  'deploy\telegram.disabled.json',
  'deploy\configure-telegram.sh',
  'deploy\set_telegram_commands.py',
  'deploy\telegram_ko\sitecustomize.py',
  'deploy\AggressiveSafeStrategy.py',
  'deploy\community_strategies\FAdxSmaStrategy.py',
  'deploy\community_strategies\FReinforcedStrategy.py',
  'deploy\trade-watch.service',
  'deploy\trade-backup.service',
  'deploy\Caddyfile.fragment',
  'README.md'
)
foreach ($relative in $requiredFiles) {
  if (-not (Test-Path (Join-Path $root $relative))) { throw "Missing file: $relative" }
}

function Assert-Contains([string]$file, [string[]]$patterns) {
  $content = Get-Content -Raw -Encoding utf8 (Join-Path $root $file)
  foreach ($pattern in $patterns) {
    if ($content -notmatch [regex]::Escape($pattern)) { throw "$file is missing: $pattern" }
  }
}

Assert-Contains 'deploy\configure-swap.sh' @('TRADE_SWAP_GB:-8', 'TRADE_SWAP_FILE:-/swapfile.trade', 'vm.swappiness=15', 'swapon --priority 10')
Assert-Contains 'deploy\freqtrade.service' @('freqtradeorg/freqtrade:stable', '--memory=800m', '-p 127.0.0.1:8080:8080', 'FReinforced20Strategy')
Assert-Contains 'deploy\freqtrade.service' @('/etc/trade-1/telegram.json:/run/secrets/telegram.json:ro', '--config /run/secrets/telegram.json')
Assert-Contains 'deploy\freqtrade.service' @('PYTHONPATH=/freqtrade/user_data/patches:/freqtrade/user_data/strategies')
Assert-Contains 'deploy\configure-telegram.sh' @('allow_custom_messages', 'notification_settings', 'systemctl restart trade-freqtrade', '--disable')
Assert-Contains 'deploy\set_telegram_commands.py' @('setMyCommands', '오늘 손익과 열린 포지션', 'Telegram command menu updated')
Assert-Contains 'deploy\telegram_ko\sitecustomize.py' @('_translate_ko', '_polish_message', '_DIVIDER', '모의투자가 활성화되어 있습니다', 'Telegram._send_msg = _send_msg_ko', 'CommandHandler(["stake", "stake_amount"]', 'CommandHandler(["daily"]', 'CommandHandler(["menu"]', 'MessageHandler(filters.Regex', 'def _remove_upstream_daily_handler', 'parse_mode=None', 'def _daily_trade_report', 'PERFORMANCE', 'OPEN POSITIONS', 'TRADE·1 COMMAND CENTER', 'def _stake_amount', '모의투자 모드에서만', 'TELEGRAM_STAKE_MAX', 'def _learn_review', 'learn_weekly', 'learn_monthly', 'latest_review_summary', 'Telegram._startup_telegram = _startup_telegram_with_stake')
Assert-Contains 'deploy\recover_journal_trades.py' @('parse_exit_messages', 'journal recovery complete', 'upsert_trade_result', 'rebuild_signal_stats')
Assert-Contains 'deploy\config.json.template' @('"dry_run": true', '"db_url": "sqlite:////freqtrade/user_data/tradesv3.dryrun.sqlite"', '"trading_mode": "futures"', '"margin_mode": "isolated"', '"max_open_trades": 3', '"stake_amount": 10', '"timeframe": "5m"', '"force_entry_enable": true', 'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', '__API_PASSWORD__')
Assert-Contains 'deploy\backtest.config.json' @('"dry_run": true', '"trading_mode": "futures"', '"margin_mode": "isolated"', '"max_open_trades": 3', 'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT')
Assert-Contains 'deploy\AggressiveSafeStrategy.py' @('can_short = True', 'timeframe = "4h"', 'stoploss = -0.08', 'return min(20.0, max_leverage)', 'position_adjustment_enable = False')
Assert-Contains 'deploy\community_strategies\FAdxSmaStrategy.py' @('class FAdxSmaStrategy', 'can_short = True', 'timeframe = "1h"', 'GPL-3.0')
Assert-Contains 'deploy\community_strategies\FReinforcedStrategy.py' @('class FReinforcedStrategy', 'class FReinforced20Strategy', 'entry_adx_threshold = 20.0', 'stoploss = -0.08', 'def protections', '"method": "CooldownPeriod"', '"stop_duration_candles": 12', 'confirm_trade_exit', 'confirm_trade_entry', 'custom_exit', 'record_entry_decision', 'should_block_signal', 'get_exit_decision', 'exit_reason == "exit_signal"', '-0.05 < current_profit < 0', 'return min(20.0, max_leverage)', 'startup_candle_count: int = 720', 'can_short = True', 'timeframe = "5m"', 'space="buy"', 'GPL-3.0')
Assert-Contains 'deploy\trade_learning.py' @('CREATE TABLE IF NOT EXISTS entry_decisions', 'CREATE TABLE IF NOT EXISTS trade_results', 'CREATE TABLE IF NOT EXISTS signal_stats', 'CREATE TABLE IF NOT EXISTS daily_reviews', 'CREATE TABLE IF NOT EXISTS weekly_reviews', 'CREATE TABLE IF NOT EXISTS monthly_reviews', 'CREATE TABLE IF NOT EXISTS learning_rules', 'MIN_PAIR_SAMPLES', 'should_block_signal', 'get_exit_decision', 'upsert_trade_result', 'rebuild_signal_stats', 'latest_review_summary')
Assert-Contains 'deploy\sync_learning.py' @('FtRestClient', 'client.trades(limit=1000)', 'client.status()', 'rebuild_signal_stats')
Assert-Contains 'deploy\review_learning.py' @('run_daily', 'run_weekly', 'run_monthly', 'pair_candles', 'daily_reviews', 'weekly_reviews', 'monthly_reviews', 'build_rule_candidates', 'take_profit', 'cut_loss')
Assert-Contains 'deploy\trade-learning-sync.service' @('docker exec --user 1000:1000 trade-freqtrade', 'sync_learning.py')
Assert-Contains 'deploy\trade-learning-sync.timer' @('OnUnitActiveSec=1min', 'Persistent=true')
Assert-Contains 'deploy\trade-learning-review-daily.timer' @('OnCalendar=*-*-* 00:10:00 UTC', 'Persistent=true')
Assert-Contains 'deploy\trade-learning-review-weekly.timer' @('OnCalendar=Mon *-*-* 00:20:00 UTC', 'Persistent=true')
Assert-Contains 'deploy\trade-learning-review-monthly.timer' @('OnCalendar=*-*-01 00:30:00 UTC', 'Persistent=true')
Assert-Contains 'deploy\install-primary.sh' @('TRADE_API_PASSWORD_FILE', 'docker pull "$FREQTRADE_IMAGE"', 'show-config', 'list-strategies', 'systemctl reload caddy', 'trade-learning-sync.timer', 'trade-learning-review-daily.timer', 'trade-learning-review-weekly.timer', 'trade-learning-review-monthly.timer', 'trade_learning.py', 'sync_learning.py', 'review_learning.py', 'recover_journal_trades.py', 'set_telegram_commands.py')
Assert-Contains 'deploy\install-standby.sh' @('trade-freqtrade', 'watch.netrc', 'docker pull "$FREQTRADE_IMAGE"')
Assert-Contains 'deploy\preflight.sh' @('At least 7 GB swap is required', 'primary', 'standby')
Assert-Contains 'deploy\backup-to-secondary.sh' @('trade-1-freqtrade-backup.tar.gz', 'user_data', 'rsync -az')
Assert-Contains 'deploy\promote-standby.sh' @('--confirm-primary-stopped', 'trade-freqtrade', 'trade-1-freqtrade-backup.tar.gz')
Assert-Contains 'deploy\Caddyfile.fragment' @('__PASSWORD_HASH__', 'reverse_proxy 127.0.0.1:8080')
Assert-Contains 'deploy\trade-backup.service' @('ReadWritePaths=/var/lib/trade-1-backup', 'NoNewPrivileges=true')
Assert-Contains 'deploy\trade-watch.service' @('ReadWritePaths=/var/lib/trade-1-watch', 'ProtectSystem=strict')

Write-Host 'Freqtrade deployment validation passed.'
