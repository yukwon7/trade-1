# trade-1 strategy tournament

Binance USD-M Perpetual 전용 비동기 paper-trading 토너먼트다. 실제 주문 엔드포인트는 없으며 `.env`의 기존 Telegram/Binance/SSH 인증값은 그대로 사용한다.

## 운영 구조

- Server 1 (`SERVER_ROLE=paper`): 8개 심볼 시세, MODE_A/B 전략 로테이션, 가상 포지션, Telegram 명령
- Server 2 (`SERVER_ROLE=analysis`): 매시간 전략별 성과 평가, 우승 전략 선정, 결과를 Server 1에 rsync
- Server 1 → Server 2: 매시 55분 SQLite online backup
- Server 2 평가/배포: 매시 58분

기본 모드는 `MODE_B`다. 매시 S01부터 S10까지 순환한다. `MODE_A`는 UTC 날짜마다 하나씩 순환한다. 분석 서버가 우승 전략을 고정하면 자동 로테이션보다 우승 전략이 우선하며, Telegram 수동 선택은 그보다 우선한다.

## 전략

| ID | 이름 | 레버리지 |
|---|---|---:|
| S01 | HA_RSI_VSA | 5x |
| S02 | EMA_CROSS_FAST | 7x |
| S03 | MACD_BB_SQUEEZE | 5x |
| S04 | ORDER_IMBALANCE_SCALP | 10x |
| S05 | RSI_DIVERGENCE | 5x |
| S06 | FUNDING_MOMENTUM | 3x |
| S07 | BREAKOUT_VOLUME | 7x |
| S08 | MEAN_REVERSION_BB | 5x |
| S09 | ICHIMOKU_CLOUD | 4x |
| S10 | VWAP_REVERT | 6x |

각 전략은 `strategies/`의 독립 모듈이다. S04는 Binance depth 20단계, S06은 실시간 funding rate와 next funding time을 사용한다. 이 두 전략은 과거 호가/펀딩 컨텍스트가 없는 일반 캔들 백테스트에서 `LIVE_ONLY`로 표시하고 live paper 표본으로 평가한다.

## 심볼과 리스크

BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX의 USDT perpetual을 5m 주기와 15m 보조 데이터로 평가한다.

- 거래당 계좌 최대 손실 2%
- 심볼당 1포지션, 전체 4포지션
- 일일 실현손실 5%에서 신규 진입 중지
- 동일 전략·심볼 3연속 손실 시 1시간 중지
- 전략 레버리지를 적용하되 10x 하드캡
- 수수료와 진입 슬리피지 반영
- 전략 청산 규칙과 별도로 모든 포지션에 보호 손절 적용

## 선정 알고리즘

전략별로 Net PnL, 승률, Profit Factor, MDD, 거래 단위 Sharpe, 거래 수를 집계한다. 심볼별 집계도 리포트 JSON에 포함한다. 10회 미만, 승률 45% 미만, PF 1.1 미만, MDD 15% 초과 전략은 제외한다.

점수는 승률 25%, 정규화 PF 30%, 정규화 Sharpe 25%, 역정규화 MDD 20%다. 최초 1위를 잠그고 72시간 이후 후보 점수가 현재 전략보다 10% 넘게 높을 때만 교체한다. 결과는 `config/tournament_result.json`으로 Server 1에 hot reload된다.

## Telegram

- `/strategy`: 현재 전략
- `/strategy S03`: 전략 수동 고정
- `/strategy auto`: 수동 고정 해제 후 자동 로테이션/우승 전략 복귀
- `/strategies`: 10개 전략 목록
- `/mode A`, `/mode B`: 로테이션 모드 변경 및 S01부터 재시작
- `/tournament`, `/rankings`: 현재 정량 순위
- `/status`, `/positions`, `/balance`, `/trades`
- `/daily`, `/weekly`, `/monthly`
- `/pause`, `/resume`

수동 전략 변경은 신규 진입에만 적용한다. 열린 포지션은 진입 당시 전략의 청산 규칙으로 끝까지 관리한다. 허용된 `.env`의 `TELEGRAM_CHAT_ID`에서 온 명령만 처리한다.

## DB

SQLite WAL을 사용한다.

- `tournament_trades`: 전략·심볼별 완료 거래와 순손익/수익률
- `tournament_positions`: 재시작 복구용 열린 포지션
- `strategy_signals`: 진입 근거와 전략 파라미터
- `tournament_reports`: 매 평가 시점 순위와 LOCK/REPLACE/CONTINUE 결과

기존 DB는 전환 전에 `data/archive/pre_tournament_UTC_TIMESTAMP/`에 보관하고 새 DB를 시작한다. `.env`는 전환 스크립트에서 읽기만 하며 수정·삭제하지 않는다.

## 실행

```bash
.venv/bin/python -m unittest discover -s tests -v
scripts/run_backtest.sh --days 30
scripts/run_analysis.sh
sudo systemctl restart trade1-paper.service
```

백테스트 결과는 `data/tournament_backtest.json`에 저장하며 실시간 우승 선정 DB와 섞지 않는다. 이 시스템은 paper trading 전용이다.
