# Open-source and methodology notices

## Current SMART FLOW QUANT engine

- The previous EMA/MACD/RSI voting and NFI-inspired breakout strategy has been replaced.
- Current analysis uses closed-candle price momentum, recent market-structure breakouts, candle pressure, relative volume when real volume is supplied, and range expansion.
- Optional real trade-flow and order-book imbalance context is fetched from Binance public Spot and USD-M Futures endpoints for a limited set of high-priority candidates. It is not available uniformly across every market.
- For equities, Saudi shares, US futures contracts and FX/metals, the engine does not invent order-flow data. It uses available candle and volume fields; some FX feeds provide tick volume or zero volume rather than centralized traded volume.
- Stop placement is based on recent swing structure with a volatility buffer. Targets are staged at 1R, 2R and 3R.
- Strength scores are confluence/ranking scores, not probabilities of profit or verified win rates.
- Binance public market-data endpoints are used without personal account API credentials. Yahoo Finance public endpoints are unofficial and may be delayed, rate-limited, geo-restricted, changed or withdrawn.
- No strategy is guaranteed profitable. Validate out of sample with commissions, spread, slippage and realistic execution assumptions.

## Retired methodology

The earlier EMA, MACD, RSI and NFI-inspired volume-breakout ensemble is no longer used by the live signal engine. Historical trades remain in the journal but are marked superseded after a successful scan under the new engine.
