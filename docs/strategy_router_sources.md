# Strategy Router Sources

This project does not copy public strategy code directly. The chart router
implements local rule-based variants inspired by common public crypto bot
strategy families and keeps them behind paper trading plus stress testing.

References reviewed:

- https://github.com/freqtrade/freqtrade
- https://github.com/freqtrade/freqtrade-strategies
- https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/Supertrend.py
- https://github.com/iterativv/NostalgiaForInfinity
- https://github.com/topics/freqtrade-strategies?o=desc&s=stars
- https://www.freqtrade.io/en/stable/strategy-101/
- https://www.reddit.com/r/algotrading/comments/1mok6i5/looking_for_feedback_on_algo_bot_settings_uses/
- https://www.reddit.com/r/algotrading/comments/1m8eqmf/any_examples_on_github_dont_have_to_be/

Implemented families:

- EMA trend pullback and breakout
- MACD histogram momentum
- Bollinger mean reversion and band ride
- VWAP reclaim/loss
- Donchian breakout
- Bollinger squeeze release
- Heikin Ashi plus RSI and volume
- RSI divergence proxy
- StochRSI proxy

Live readiness remains controlled by `analytics.stress_tester`; public popularity
or repository stars are not treated as proof of profitability.
