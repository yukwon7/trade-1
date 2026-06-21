# trade-1

Binance USDT-M Futures 전용 비동기 paper-trading 및 분석 플랫폼이다. 실제 주문 코드는 없으며 Binance API 키는 읽기 전용으로만 사용한다.

## 아키텍처

### Server 1 — `SERVER_ROLE=paper`

- 1H·15M·5M 종가 데이터를 비동기로 수집한다.
- 1H 추세 → 15M 방향 → 5M 돌파 순서로 신호를 평가한다.
- 점수, 레버리지, 리스크 기반 수량을 계산해 가상 포지션을 관리한다.
- 거래·신호·지표를 `data/trades.db`에 SQLite WAL로 기록한다.
- Telegram으로 진입, 추가매수, 부분청산, 전체청산을 알리고 운영 명령을 처리한다.
- 매시간 SQLite online backup을 만든 뒤 Server 2로 `rsync`한다.

### Server 2 — `SERVER_ROLE=analysis`

- 매일 00:00 UTC 최근 거래를 분석하고 `config/config_override.json`을 갱신한다.
- 4시간마다 USD-M Futures 전체 ticker를 한 번 조회해 거래대금 상위 15개를 선정한다.
- 분석·백테스트·일일 리포트를 실행한다.
- 갱신된 override와 symbol 파일을 Server 1에 즉시 `rsync`한다.

Server 1은 두 JSON 파일의 mtime을 매 거래 사이클 확인하므로 재시작 없이 반영한다.

## 전략

필수 방향 조건:

- LONG: 1H EMA20 > EMA50, 15M EMA20 > EMA50, 5M 저항 돌파, RSI > 50, Volume Ratio > 1.2
- SHORT: 1H EMA20 < EMA50, 15M EMA20 < EMA50, 5M 지지 이탈, RSI < 50, Volume Ratio > 1.2
- 5M ADX < 20이면 무조건 진입하지 않는다.

점수는 Trend 30, Momentum 20, Volume 20, Breakout/Retest 20, ATR 안정성 10으로 총 100점이다. 기본 진입선은 65점이다.

레버리지:

- 85점 이상: 5x
- 75점 이상: 3x
- 65점 이상: 2x
- 65점 미만: 진입 금지

포지션당 최대 손실은 잔고의 1%이며, 최초 손절 거리는 진입 시점 5M ATR × 1.5로 고정한다. 최초 진입은 계획 수량의 40%이고, 수익 상태와 추세가 유지될 때만 25%·20%·15%를 추가한다. 1R에서 본전 스탑, 2R에서 50% 부분청산, 나머지는 ATR × 1.0 트레일링 스탑을 사용한다.

PnL에는 양방향 수수료 0.04%와 진입 슬리피지 0.05%가 포함된다.

## 리스크 제한

- 일일 손실 3%: 당일 신규 진입 중지
- 3연속 손실: 1시간 중지
- 동일 심볼 손절: 30분 쿨다운
- 동일 심볼 최근 10회 중 7회 손실: 6시간 중지
- 동시 포지션 기본 5개
- 모니터링 심볼 하드캡 15개
- 실주문 엔드포인트 및 주문 권한 없음

제한 상태는 `trades.db`에서 재구성되므로 프로세스 재시작으로 초기화되지 않는다.

## 폴더

```text
trade-1/
├── main.py                     # Server 1 paper 엔진
├── config.py                   # .env + JSON 핫 리로드
├── models.py
├── exchange/                   # Binance USD-M read-only client
├── scanner/                    # Server 2 거래대금 스캐너
├── indicators/                 # EMA/RSI/ADX/ATR/Volume
├── strategy/                   # MTF 신호 및 점수
├── risk/                       # 레버리지/수량/SL/피라미딩/차단
├── trader/                     # 다중 paper position 엔진
├── storage/                    # SQLite WAL 및 repository
├── analytics/                  # 성과/패턴/최적화/백테스트
├── reports/                    # 일일 리포트
├── notify/                     # Telegram
├── config/                     # override 및 selected symbols
├── scripts/                    # 초기화/설치/동기화/실행
├── systemd/                    # paper/analysis 서비스 예시
└── tests/
```

## 설정 파일

### `.env`

시크릿과 서버별 고정 설정만 둔다. `.env.example`을 복사해 사용하며 Git에 커밋하지 않는다. `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`, SSH 키 경로는 코드에 기록하지 않는다.

### `config/config_override.json`

Server 2만 생성·수정한다.

- `MIN_SCORE`: 최소 진입 점수
- `MAX_LEVERAGE`: 1~5
- `TRADE_FREQUENCY_MULTIPLIER`: PF 악화 시 20%씩 축소
- `PYRAMIDING_ENABLED`: 추가매수 활성화
- `SYMBOL_BLACKLIST`: 신규 진입 제외 목록
- `_stability`: 자동 원복을 위한 3일 연속 회복 카운터
- `updated_at`, `reason`: 변경 시각과 근거

승률 45% 미만이면 점수 +5, PF 1.1 미만이면 빈도 20% 감소, MDD 8% 초과면 레버리지 -1이다. 승률 55%, PF 1.3, MDD 5% 미만이 각각 3일 유지되면 한 단계씩 원복한다. 추가매수 5연속 손실은 자동 비활성화하며 수동으로만 재활성화한다. 거래 100건 미만이면 최적화를 건너뛴다.

### `config/selected_symbols.json`

스캐너 결과와 생성 시각을 담는다. 파일이 없으면 BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK, SUI를 사용한다. 15개 초과 입력은 앞에서 15개만 적용하며 스캐너 출력은 거래대금 내림차순이다.

## DB 스키마

- `trades`: 완료 거래, 비용, PnL, 보유시간, 종료 사유
- `positions`: 재시작 복구용 열린 포지션 전체 상태
- `signals`: 점수 구성과 진입 시 지표
- `indicator_snapshots`: 심볼·타임프레임별 지표
- `daily_stats`: 승률, PF, PnL, MDD
- `optimizer_logs`: 분석 지표와 설정 변경 전후

`journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`을 적용한다.

## 최초 배포

두 서버 모두 Ubuntu 사용자 `ubuntu`, 프로젝트 경로 `/opt/trade-1`을 기준으로 한다.

1. 기존 서버에서 시크릿을 `.env`로 복원한다.

   ```bash
   sudo SERVER_ROLE=paper /opt/trade-1/scripts/restore_env.sh   # Server 1
   sudo SERVER_ROLE=analysis /opt/trade-1/scripts/restore_env.sh # Server 2
   ```

2. `reset_trade1.sh`는 역할·`.env`·필수 키·타임스탬프 백업을 모두 확인한 뒤에만 기존 코드를 삭제한다. 백업은 `/opt/trade-1-backups/backup_YYYYMMDD_HHMMSS/`에 생성된다.

3. 새 코드를 `/opt/trade-1`에 배치하고 보존한 `.env`를 되돌린다.

4. 설치한다.

   ```bash
   cd /opt/trade-1
   sudo apt-get update
   sudo apt-get install -y python3-venv rsync curl
   ./scripts/install.sh
   ```

5. Server 1은 `trade1-paper.service`가 즉시 시작된다. Server 2는 cron이 00:00 UTC 분석, 4시간 간격 스캐너를 실행한다.

## 서버 간 SSH/rsync

각 서버의 `.env`에 반대 서버 주소, `RSYNC_USER`, `RSYNC_SSH_KEY`를 설정한다. 공개키는 상대 서버 `~/.ssh/authorized_keys`에 읽기/쓰기 범위를 고려해 등록한다.

- Server 1 → Server 2: 매시 55분, SQLite online backup 후 `data/trades.db` 전송
- Server 2 → Server 1: optimizer/scanner 완료 직후 두 JSON 전송

수동 확인:

```bash
scripts/sync_trades_to_analysis.sh
scripts/run_scanner.sh
scripts/run_analysis.sh
```

## 실행 및 검증

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m analytics.backtester --symbol BTCUSDT --days 90
sudo systemctl status trade1-paper.service
sudo journalctl -u trade1-paper.service -f
```

## Telegram 명령

- 상태: `/status`, `/positions`, `/balance`, `/profit`, `/count`
- 성과: `/daily`, `/weekly`, `/monthly`, `/trades`, `/performance`
- 복기: `/learn`, `/learn_weekly`, `/learn_monthly`
- 설정 확인: `/symbols`, `/config`, `/stake`
- 신규 진입 중지: `/pause` 또는 `/stop`
- 신규 진입 재개: `/resume` 또는 `/start`

중지 상태는 `config/paper_state.json`에 저장되어 재시작 후에도 유지된다. 중지 중에도 기존 포지션의 손절·익절은 계속 실행된다. Telegram 명령은 `.env`의 `TELEGRAM_CHAT_ID`와 일치하는 채팅에서만 허용한다.

이 프로젝트는 paper trading 전용이다. 백테스트·forward test가 충분한 수익성과 안정성을 입증하기 전에는 실제 주문 기능을 추가하지 않는다.
