# 자동매매 엔진 재선정

조사일: 2026-06-19

초기에는 1 OCPU·1GB RAM 제약과 웹 UI 편의성 때문에 OctoBot을 선택했다. 이후 요구가 선물 2배 레버리지, 명시적 포지션 크기, 손절, Long/Short, 재현 가능한 백테스트로 변경되어 Freqtrade로 전환했다.

## 선택 근거

- Freqtrade는 Dry-run, 선물, 전략별 레버리지 callback, 손절, 백테스트와 FreqUI를 공식 지원한다.
- 현재 서버는 물리 RAM이 작으므로 swap 8GB를 OOM 완충용으로 구성한다.
- swap은 성능을 높이지 않으므로 백테스트와 Hyperopt는 가능하면 로컬 고사양 환경에서 수행한다.
- Primary만 실행하고 Standby는 중지 상태를 유지한다.
- 실거래 전환은 이 프로젝트의 범위가 아니며 API 키를 배포하지 않는다.

## 위험 한도

- 격리 마진 2배 이하
- 100 USDT 증거금, 동시 1포지션
- 8% 거래위험 손절
- 16% 거래위험 익절
- 포지션 추가매수 금지
- 90일 이상 백테스트와 최소 수 주 dry-run 검증
- 최대 낙폭과 손실 연속 횟수를 수익률보다 우선 평가

## 최초 1년 백테스트

- 4시간 BTC/USDT:USDT, 격리 선물 2배
- 48회 거래, 총수익률 -1.09%
- 최대 낙폭 4.03%, Profit factor 0.92
- 위험 제한은 작동했지만 기대수익이 음수이므로 실거래 부적합

## 5개 신호 모델 비교 (2026-06-20)

### 참고 자료

- [Freqtrade 공식 전략 작성 문서](https://www.freqtrade.io/en/stable/strategy-customization/): 완성된 캔들만 사용하고 startup candle을 확보하는 원칙을 적용했다.
- [Freqtrade 공식 백테스트 문서](https://www.freqtrade.io/en/stable/backtesting/): 정적 페어 목록, 동일 시작 잔고, 명시적 수수료로 재현 가능한 비교를 구성했다.
- [Freqtrade 공식 lookahead-analysis 문서](https://www.freqtrade.io/en/stable/lookahead-analysis/): 우승 후보에 미래 데이터 참조 검사를 수행한다.
- [freqtrade/freqtrade-strategies FSupertrendStrategy](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/futures/FSupertrendStrategy.py): ATR 기반 Supertrend 방향 전환 구조를 참고했다.
- [freqtrade/freqtrade-strategies BbandRsi](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/BbandRsi.py): Bollinger Band와 RSI 평균회귀 조합을 참고했다.
- [AQR Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum): 시계열 모멘텀과 추세 지속성의 연구 근거를 참고했다.
- [John Bollinger의 공식 Bollinger Band 규칙](https://www.bollingerbands.com/bollinger-band-rules): 밴드 접촉 하나만으로 신호를 확정하지 않고 RSI·ADX 확인 조건을 결합했다.

### 후보

1. `ModelEmaAdxTrend`: EMA 20/50/200 + ADX + RSI 추세 추종
2. `ModelBollingerRsiReversion`: Bollinger 2.2σ + RSI + 저ADX 평균회귀
3. `ModelDonchianAtrBreakout`: Donchian 24봉 돌파 + ATR + 거래량
4. `ModelMacdMomentum`: MACD 교차 + EMA200 + RSI/ADX 모멘텀
5. `ModelSupertrendConsensus`: ATR Supertrend 전환 + EMA200 + RSI

### 공정 비교 조건

- Binance USDT 무기한 선물 BTC·ETH·SOL, 15분봉
- 동일 격리 5배, 포지션당 100 USDT, 동시 최대 3개
- 동일 손절 -3%, 단타 ROI 2%→1.2%→0%, 동일 추적익절
- 진입·청산 각각 0.04% 수수료
- 개발 구간 `2025-06-18~2026-03-18`, 검증 구간 `2026-03-18~2026-06-19`
- 검증 구간에서 양의 총수익과 충분한 거래 수를 만족한 후보 중 승률 1위를 선택

### 최종 검증 결과

사용자 요청에 따라 최종 조건을 격리 5배, 손절 -3%, 단타 ROI 2%→1.2%로 변경하고
미사용 최근 3개월(`2026-03-18~2026-06-19`)을 다시 검증했다.

| 모델 | 거래 | 승률 | 총수익 | 최대낙폭 | 판정 |
|---|---:|---:|---:|---:|---|
| ModelEmaAdxTrend | 94 | 58.5% | -3.20% | 3.98% | 제외 |
| ModelBollingerRsiReversion | 614 | 61.6% | -16.42% | 19.47% | 제외 |
| ModelDonchianAtrBreakout | 1,131 | 59.0% | -21.27% | 23.29% | 제외 |
| **ModelMacdMomentum** | **508** | **53.5%** | **+0.01%** | **4.05%** | **선택** |
| ModelSupertrendConsensus | 343 | 60.1% | -7.06% | 8.83% | 제외 |

승률만 보면 Bollinger/RSI가 가장 높지만 총손실 모델을 배포하지 않는 사전 기준에 따라 제외했다.
양의 총수익을 만족한 후보 중 승률 1위인 `ModelMacdMomentum`을 dry-run 전략으로 선택했다.
수익 우위가 매우 작으므로 실거래 근거가 아니며, 일·주·월 복기와 추가 dry-run 검증을 계속한다.
