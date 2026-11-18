# AS Trading Knowledge Curriculum v1

## Purpose
A structured, expandable curriculum for AS Quant Intelligence. This is a knowledge and research catalog, not proof that a strategy is profitable and not authorization for live orders. Every method must have an explicit rule specification, data requirements, implementation status, tests, and evidence record.

## Learning architecture
1. **Learn**: store definitions, assumptions, market applicability, entry/exit rules, failure modes, and source references.
2. **Formalize**: translate each method into deterministic, versioned rules. No vague labels such as "smart money confirmed".
3. **Validate data**: check timestamps, missing bars, duplicates, corporate actions, contract rolls, symbol mapping, and candle completeness.
4. **Backtest**: chronological train/validation/test splits; realistic fees, spread, slippage, funding, borrow and execution constraints where applicable.
5. **Walk-forward**: repeat across rolling windows and market regimes; prohibit look-ahead and survivorship bias.
6. **Paper forward-test**: simulate signals with timestamped prices and persist every candidate, fill assumption, exit and outcome.
7. **Qualify**: report sample size, net expectancy, win rate, profit factor, max drawdown, exposure, turnover, tail loss, regime breakdown and uncertainty.
8. **Promote**: research-only -> paper-qualified -> shadow production -> human-approved production. Promotion requires explicit review; never self-promote.
9. **Monitor**: detect data drift, performance decay, execution mismatch and stale feeds; automatically disable a method when safety/data checks fail.

## Knowledge domains and strategy families

### 1. Price action and classical technical analysis
Candlesticks and multi-candle patterns; market structure; trendlines and channels; support/resistance; breakouts and retests; false breakouts; gaps; chart patterns (triangles, flags, wedges, head-and-shoulders, double tops/bottoms); pivot points; Dow Theory; Wyckoff phases; volatility contraction/expansion.

### 2. Trend and momentum
Moving-average systems; moving-average crossovers; MACD; ADX/DMI; Donchian breakouts; channel breakouts; time-series momentum; cross-sectional momentum; relative strength; pullback continuation; volatility-adjusted trend; turtle-style rules.

### 3. Mean reversion and range trading
RSI/Stochastic extremes; Bollinger mean reversion; Keltner channels; z-score reversion; distance from VWAP/anchored VWAP; pairs and spread reversion; range rotation; failed auction/re-entry. Require regime filters because persistent trends can make reversion fail.

### 4. Liquidity, auction theory and market structure
Liquidity sweeps; stop runs; failed auctions; order blocks; fair-value gaps; BOS/CHoCH; premium/discount; opening range; session highs/lows; volume profile (POC, VAH, VAL); market profile; auction-market theory; Wyckoff accumulation/distribution. ICT/SMC labels must be operationally defined and tested, not treated as evidence by themselves.

### 5. Volume and order flow
Volume/relative volume; OBV; A/D line; VWAP; volume profile; footprint; bid/ask delta; cumulative volume delta; absorption; imbalance; depth/order-book imbalance; trade flow. Footprint, depth and true order-flow methods require suitable timestamped exchange data; OHLCV proxies must be labeled as proxies.

### 6. Statistical and quantitative methods
Descriptive statistics; distributions; robust statistics; hypothesis testing; bootstrap confidence intervals; correlation/covariance; cointegration; pairs trading; factor models; volatility forecasting; GARCH-family models; regime switching; Kalman filters; Monte Carlo; Kelly as a theoretical upper bound with conservative fractional sizing. Account for multiple-testing and selection bias.

### 7. Machine learning and AI
Linear/logistic models; tree ensembles; gradient boosting; random forests; clustering; dimensionality reduction; hidden Markov models; anomaly detection; sequence models; deep learning; reinforcement learning research. Require leakage-safe features, chronological validation, calibration, explainability, drift monitoring and a simple baseline. LLMs may explain research but must not fabricate market data or be treated as a price oracle.

### 8. Fundamental and company analysis
Financial statements; revenue/earnings/cash flow; balance sheet quality; valuation multiples; DCF; growth and quality factors; earnings revisions; guidance; insider/institutional ownership where reliable. Primarily relevant to equities; not directly transferable to FX or crypto without adaptation.

### 9. Macro, rates and intermarket analysis
Central-bank policy; rates/yield curves; inflation; employment; liquidity; fiscal policy; USD; commodities; real yields; risk-on/risk-off; cross-asset correlations; economic calendar and event risk. Use timestamped releases and point-in-time data to avoid look-ahead.

### 10. Derivatives and positioning
Futures basis; funding; open interest; liquidations; term structure; contango/backwardation; options Greeks; implied/realized volatility; skew; put/call; gamma exposure only with valid options-chain inputs. Never infer options positioning from spot candles.

### 11. Sentiment and news
News classification; event extraction; social sentiment; positioning surveys; analyst revisions; sentiment breadth. Track source, timestamp, coverage and manipulation risk. Missing or low-quality feeds mean unavailable, not neutral.

### 12. Risk, portfolio construction and execution
Fixed-fractional sizing; volatility targeting; ATR stops; structural stops; risk/reward; portfolio heat; correlation and concentration; drawdown controls; exposure caps; liquidity constraints; limit/market execution simulation; fees, spread, slippage, funding, borrow and partial fills. Risk controls are mandatory gates, not optional signals.

## Market adapters
Maintain separate adapters and evidence for Binance Spot, Binance Futures, Alpha, US equities, US contracts, Saudi equities, and FX/metals. Each adapter must declare supported symbols, sessions, trading calendar, contract specifications, shorting rules, fees, funding/borrow, data source, update cadence and known gaps. Never reuse a market's assumptions silently in another market.

## Timeframes
Support 15m, 1h, 4h, 1d, 1w and 1M where source history permits. Align bars to exchange calendars and timezone. Exclude incomplete bars from signal confirmation. Higher-timeframe context is a feature, not an unconditional direction override.

## Required method record
- method_id, family, version, description
- formal entry, exit, invalidation and sizing rules
- required fields and data source
- supported markets/timeframes
- implementation status: catalog_only / data_required / research_implemented / tested / paper_qualified
- known failure modes and assumptions
- test dates, sample size and all performance metrics
- code fingerprint and reproducibility metadata

## Release gates
- No live order placement from this curriculum.
- No claim of "learned", "AI trained", "best", or "profitable" without reproducible evidence.
- No live promotion based on in-sample results.
- Do not delete losing experiments or rewrite historical outcomes.
- Do not blend conflicting strategy candidates into one score without a documented, validated ensemble.
- Current PR #366 research engine remains isolated until integration tests, persistent paper ledger, 24/7 worker health, and qualification gates are complete.

## Initial implementation priority
1. Expand catalog and method metadata.
2. Add data-quality and point-in-time validation.
3. Add reproducible backtest harness with costs.
4. Add persistent paper-trade ledger and outcome resolver.
5. Add walk-forward and regime reports.
6. Add Academy dashboard with honest statuses and missing-data requirements.
7. Only then evaluate shadow integration; keep human approval and manual execution.
