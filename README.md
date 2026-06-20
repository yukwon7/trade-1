# trade-1

Oracle Cloud 저사양 서버 2대를 사용하는 Freqtrade 자동매매 운영 프로젝트다. Primary만 거래 엔진을 실행하고 Standby는 감시·백업·수동 장애 전환을 담당한다.

현재 운영 모드는 Binance USDT 무기한 선물 `dry-run`이며 실거래 API 키를 사용하지 않는다.

Freqtrade 거래 DB는 `/opt/trade-1/user_data/tradesv3.dryrun.sqlite`에 저장한다. 컨테이너 재시작 후에도 dry-run 거래내역이 유지되고 백업 대상에 포함된다.

## 서버

- Primary: `168.107.21.178`
- Standby: `140.245.73.101`
- FreqUI: `https://trade1.blockpixel.duckdns.org`

## 모의 전략

- 활성 전략: `ModelMacdMomentumLoose150` (15분봉 완화형, 격리 5배, 손절 -3%, 단타 ROI)
- 페어: `BTC/USDT:USDT`, `ETH/USDT:USDT`, `SOL/USDT:USDT`
- 동시 포지션: 최대 3개
- 롱/숏 레버리지: 거래소 허용 범위 내 최대 5배
- 타임프레임: 15분
- 방향: Long/Short
- 마진: 격리
- 모의지갑: 1,000 USDT
- 주문 증거금: 기본 100 USDT (텔레그램 `/stake`로 변경 가능)
- 손실 청산: -3% 하드 손절
- 추가매수: 비활성화
- 학습 DB: 진입 당시 지표와 청산 결과를 SQLite에 저장하고, 충분한 표본에서 성과가 나쁜 자동 신호만 보수적으로 차단

이 구성은 수익을 보장하지 않는다. 백테스트와 장기 dry-run 결과 없이 `dry_run`을 끄지 않는다.

## 거래 학습 DB

- DB 경로: Primary `/opt/trade-1/user_data/learning/trade_learning.sqlite`
- `entry_decisions`: 자동/수동 진입 시점의 페어, 방향, 태그, 가격, 레버리지, EMA/SMA/ADX/거래량 조건, 허용/차단 여부를 기록한다.
- `trade_results`: Freqtrade API의 열린/종료 거래를 1분마다 동기화하고, 손익 여부와 청산 사유를 한국어 설명으로 저장한다.
- `signal_stats`: 종료된 자동 거래를 페어·방향·진입태그별로 집계한다.
- `daily_reviews`: 매일 하루 거래와 5분봉 시장 데이터를 복기해 좋았던 자리/안 좋았던 자리를 저장한다.
- `weekly_reviews`: 매주 일일 복기를 종합해 반복 강점/약점과 진입·익절·손절 규칙 후보를 저장한다.
- `monthly_reviews`: 매월 주간·일일 복기를 다시 종합해 장기 공통점을 저장한다.
- `learning_rules`: 복기에서 충분히 반복된 약한 진입, 학습 익절, 학습 손절 후보를 전략이 읽는 규칙으로 저장한다.

자동 신호는 같은 페어·방향·태그에서 종료 표본 20개 이상, 승률 35% 미만, 평균 손익 음수일 때만 차단한다. 전체 페어 기준은 표본 30개 이상일 때 적용한다. 사용자가 텔레그램/FreqUI에서 넣는 수동·강제 진입은 학습 차단 대상이 아니다.

복기 자동 실행:

- 일일 복기: 매일 00:10 UTC
- 주간 복기: 매주 월요일 00:20 UTC
- 월간 복기: 매월 1일 00:30 UTC

텔레그램에서 `/learn`, `/learn_weekly`, `/learn_monthly`로 최신 복기를 확인할 수 있다. 학습 손절/익절은 충분한 표본이 생긴 규칙만 dry-run 전략에 반영된다.

## 현재 검증 결과

- 기간: 2025-07-24 ~ 2026-06-18
- 거래: 48회
- 총수익률: -1.09%

## 추가 커뮤니티 전략

출처는 GPL-3.0인 [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) 커밋 `dbd5b0b`이다. 2025-12-21~2026-06-18 Binance 선물 BTC·ETH·SOL, 초기자금 1,000 USDT, 포지션당 100 USDT, 동시 3개 조건의 비교 결과다.

- `FAdxSmaStrategy`: 1시간봉, 롱·숏, 32회, 총수익률 -0.50%
- `FReinforcedStrategy`: 5분봉+1시간 추세 필터, 롱·숏, 총수익률 -1.86%; Freqtrade 2026.5.1 호환성 수정 포함
- `ModelMacdMomentumLoose150`: MACD 교차를 EMA150·완화 RSI·ADX 15로 확인하는 5배 Long/Short 단타 전략

현재 활성 전략은 기존 MACD 모델보다 3개월 거래 수를 508회에서 817회로 늘리면서 +0.44%를 기록한 `ModelMacdMomentumLoose150`이다. 5분봉 후보는 같은 3개월 구간에서 손실이어서 배포하지 않았다. 백테스트는 미래 수익을 보장하지 않으며 계속 dry-run으로 검증한다.
- 최대 낙폭: 4.03%
- Profit factor: 0.92

현재 전략은 수익성 기준을 통과하지 못했으므로 forward 테스트 전용이다. 실거래 전환 금지.

## 배포

1. 양쪽 서버에서 `sudo TRADE_SWAP_GB=8 bash deploy/configure-swap.sh`를 실행해 기존 1GB에 8GB swap을 추가한다.
2. Primary에서 dashboard hash, API password, 백업 SSH 키를 준비한다.
3. Primary preflight와 `install-primary.sh`를 실행한다.
4. Standby preflight와 `install-standby.sh`를 실행한다.
5. 데이터를 내려받아 백테스트한 뒤 Primary의 `trade-freqtrade`만 시작한다.
6. Standby의 `trade-freqtrade`는 항상 중지 상태로 유지한다.

## 텔레그램 모니터링

텔레그램은 기본적으로 꺼져 있다. BotFather에서 봇을 만들고 해당 봇에 메시지를 한 번 보낸 뒤 숫자형 chat ID를 확인한다. 토큰과 ID를 각각 Primary 서버의 제한된 파일에 저장하고 다음 명령을 실행한다.

```bash
sudo trade-1-configure-telegram /secure/telegram-token /secure/telegram-chat-id
```

봇은 시작, 상태, 경고, 모의 진입·체결·청산을 알린다. 실거래를 활성화하지 않으며 사용자 정의 메시지도 허용하지 않는다. 비활성화 명령은 `sudo trade-1-configure-telegram --disable`이다.

발신 메시지는 `user_data/patches/sitecustomize.py` 패치로 한국어 번역된다. Freqtrade 호환성을 위해 `/status`, `/profit`, `/balance`, `/help` 같은 명령어 이름은 영문을 유지한다.

추가 명령:

- `/stake`: 현재 포지션당 증거금을 표시한다.
- `/stake 20`: 다음 신규 포지션부터 사용할 증거금을 20 USDT로 변경한다.
- `/daily`: 한국시간 기준 오늘 진입·청산, 실현·미실현 손익, 현재 열린 포지션을 표시한다.
- `/menu`: 카드형 명령 센터를 표시한다. `/help`와 동일하다.
- `/learn`: 최근 일일 복기를 표시한다.
- `/learn_weekly`: 최근 주간 복기를 표시한다.
- `/learn_monthly`: 최근 월간 복기를 표시한다.

이 명령은 `dry_run` 설정에서만 동작하며 기본 허용 범위는 1~100 USDT다. 이미 열린 포지션에는 적용되지 않는다.

텔레그램 출력은 `sitecustomize.py`의 공통 UI 포맷터를 거쳐 제목, 상태 아이콘, 구분선,
정보 우선순위를 일관되게 표시한다. 시작·경고·진입·청산 알림과 주요 명령 화면에 동일하게 적용된다.

컨테이너 교체 전에 거래 DB가 영속화되지 않아 과거 DB를 잃었지만 systemd journal이 남아 있는 경우,
완료 거래를 학습 DB로 일회성 복구할 수 있다.

```bash
sudo journalctl -u trade-freqtrade -o json --no-pager | \
  sudo docker exec -i --user 1000:1000 trade-freqtrade \
  python /freqtrade/user_data/strategies/recover_journal_trades.py
```

## 운영 명령

```bash
sudo systemctl status trade-freqtrade
sudo journalctl -u trade-freqtrade -f
sudo systemctl stop trade-freqtrade
sudo systemctl start trade-freqtrade
docker logs -f trade-freqtrade
```

대시보드/API 암호는 `.secrets/dashboard-password.txt`에만 저장한다.
