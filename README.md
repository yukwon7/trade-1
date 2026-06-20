# trade-1

Oracle Cloud 저사양 서버 2대를 사용하는 Freqtrade 자동매매 운영 프로젝트다. Primary만 거래 엔진을 실행하고 Standby는 감시·백업·수동 장애 전환을 담당한다.

현재 운영 모드는 Binance USDT 무기한 선물 `dry-run`이며 실거래 API 키를 사용하지 않는다.

## 서버

- Primary: `168.107.21.178`
- Standby: `140.245.73.101`
- FreqUI: `https://trade1.blockpixel.duckdns.org`

## 모의 전략

- 활성 전략: `FReinforced20Strategy`
- 페어: `BTC/USDT:USDT`, `ETH/USDT:USDT`, `SOL/USDT:USDT`
- 동시 포지션: 최대 3개
- 롱/숏 레버리지: 거래소 허용 범위 내 최대 20배
- 타임프레임: 5분 (1시간 추세 필터)
- 방향: Long/Short
- 마진: 격리
- 모의지갑: 1,000 USDT
- 주문 증거금: 10 USDT
- 손실 청산: -5% 전에는 전략 청산 거부, -5%부터 전략 청산 허용, -8% 하드 손절
- 재진입 대기: 청산 후 같은 페어 12개 봉(1시간)
- 추가매수: 비활성화
- 학습 DB: 진입 당시 지표와 청산 결과를 SQLite에 저장하고, 충분한 표본에서 성과가 나쁜 자동 신호만 보수적으로 차단

이 구성은 수익을 보장하지 않는다. 백테스트와 장기 dry-run 결과 없이 `dry_run`을 끄지 않는다.

## 거래 학습 DB

- DB 경로: Primary `/opt/trade-1/user_data/learning/trade_learning.sqlite`
- `entry_decisions`: 자동/수동 진입 시점의 페어, 방향, 태그, 가격, 레버리지, EMA/SMA/ADX/거래량 조건, 허용/차단 여부를 기록한다.
- `trade_results`: Freqtrade API의 열린/종료 거래를 1분마다 동기화하고, 손익 여부와 청산 사유를 한국어 설명으로 저장한다.
- `signal_stats`: 종료된 자동 거래를 페어·방향·진입태그별로 집계한다.

자동 신호는 같은 페어·방향·태그에서 종료 표본 20개 이상, 승률 35% 미만, 평균 손익 음수일 때만 차단한다. 전체 페어 기준은 표본 30개 이상일 때 적용한다. 사용자가 텔레그램/FreqUI에서 넣는 수동·강제 진입은 학습 차단 대상이 아니다.

## 현재 검증 결과

- 기간: 2025-07-24 ~ 2026-06-18
- 거래: 48회
- 총수익률: -1.09%

## 추가 커뮤니티 전략

출처는 GPL-3.0인 [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) 커밋 `dbd5b0b`이다. 2025-12-21~2026-06-18 Binance 선물 BTC·ETH·SOL, 초기자금 1,000 USDT, 포지션당 100 USDT, 동시 3개 조건의 비교 결과다.

- `FAdxSmaStrategy`: 1시간봉, 롱·숏, 32회, 총수익률 -0.50%
- `FReinforcedStrategy`: 5분봉+1시간 추세 필터, 롱·숏, 총수익률 -1.86%; Freqtrade 2026.5.1 호환성 수정 포함
- `FReinforced20Strategy`: ADX 20 이상 추세 정렬에서 진입하는 20배·증거금 10 USDT 드라이런 변형

현재 활성 전략은 `FReinforced20Strategy`이며 수익성이 입증된 전략은 아니다. NFI 계열은 40~80페어와 6~12개 포지션을 권장하고 계산량과 포지션 추가 진입이 커 현재 서버 구성에서는 제외했다.
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

## 운영 명령

```bash
sudo systemctl status trade-freqtrade
sudo journalctl -u trade-freqtrade -f
sudo systemctl stop trade-freqtrade
sudo systemctl start trade-freqtrade
docker logs -f trade-freqtrade
```

대시보드/API 암호는 `.secrets/dashboard-password.txt`에만 저장한다.
