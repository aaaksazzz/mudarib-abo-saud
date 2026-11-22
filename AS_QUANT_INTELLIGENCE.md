# AS Quant Intelligence

AS SMART TRADING PRO is the product identity. The research engine fingerprint is
`AS-QUANT-INTELLIGENCE-V1-20261118`.

## Purpose
Build an evidence-led, adaptive market-analysis system that can test many analytical
schools independently. The engine is not described as superior to human analysts until
a fair, repeatable, out-of-sample comparison demonstrates that claim.

## Research families
- Price action and market structure
- Trend following and moving-average systems
- Momentum and breakout systems
- Mean reversion and range trading
- Volume and VWAP / volume-profile research
- Smart Money / ICT and liquidity models
- Quantitative statistics, volatility and regime classification
- Order flow and market microstructure (requires reliable trades/order-book feeds)
- Options and derivatives (requires options-chain / Greeks data)
- Fundamental, macro, earnings and event analysis (requires timestamped source adapters)
- News and sentiment (requires attributable, timestamped sources)
- Portfolio construction and risk management (requires portfolio inputs)

## Current code status
The first research-only implementation is in `as_quant_intelligence.py`.
It implements OHLCV-based trend-pullback, momentum-breakout, mean-reversion and
range-structure candidate generators, plus a basic regime classifier. The catalog
marks data-dependent methods as requiring adapters. This module does not replace
the production strategy and does not claim to have trained an AI model.

## Safety and qualification gates
- Candidate scores are heuristic quality scores, not probabilities.
- Opposing candidates are exposed as conflicts; they are not averaged or arbitrarily voted.
- Spot is BUY-only.
- No live order execution. Paper/research only.
- No strategy is promoted without realistic costs, chronological train/validation/test,
  walk-forward and forward-paper evidence.
- Report sample size, net expectancy, profit factor, drawdown and uncertainty.
- Keep negative experiments; do not erase failures.
- Never use forming candles, future data, leaked labels or survivorship-biased universes.

## Brand
Use **AS** as the visible mark and **AS SMART TRADING PRO** as the product name.
