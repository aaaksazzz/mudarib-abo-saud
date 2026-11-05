# Open-source and public-data notices

## Strategy references and implementation boundaries

SMART TRADING PRO is a manual market-analysis terminal. It does not execute orders or embed a third-party trading bot.

- **NostalgiaForInfinity** — https://github.com/iterativv/NostalgiaForInfinity  
  Upstream license: GPL-3.0. Its public documentation recommends a 5-minute Freqtrade setup and points to commit-level backtest notes. This application does not vendor NFI source files or claim to reproduce the complete NFI strategy. The new signal ensemble uses only general, independently implemented ideas for volume/momentum confirmation and market-regime filtering.

- **Freqtrade Strategies That Work** — https://github.com/paulcpk/freqtrade-strategies-that-work  
  Upstream license: MIT. Its published EMA, MACD and RSI trend conditions are represented as independent votes in this application's clean-room implementation. The upstream README reports historical 1-hour tests from 2018-03-01 to 2020-03-01; those figures are not results for SMART TRADING PRO and are not a verified live win rate.

- **Freqtrade** — https://github.com/freqtrade/freqtrade  
  Upstream license: GPL-3.0. Freqtrade is a bot and backtesting framework, not a single trading strategy. It is not installed as an application dependency and no automatic order execution is enabled here.

## Current strategy engine

- Every supported market and timeframe is evaluated independently using closed candles.
- The ensemble uses EMA trend, MACD trend, RSI trend and an NFI-inspired volume breakout vote. At least two aligned votes are required.
- Stop distance is 1 ATR; staged targets are 1R, 2R and 3R.
- The displayed strength is a confluence score, not a probability of profit or verified win rate.
- No strategy is guaranteed profitable. Fees, spread, slippage, provider delays and market regime can materially change results.

## Public market-data endpoints

- Binance Spot, USD-M Futures and Alpha public market-data endpoints are used without personal account API keys.
- Yahoo Finance public chart and screener endpoints are used without an API key. These endpoints are unofficial and may be delayed, rate-limited, geo-restricted, changed or withdrawn.
- The Saudi and US equity symbol lists are discovered through Yahoo's public screener. Screener responses are bounded and do not prove every listing is present.
