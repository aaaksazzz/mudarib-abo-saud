# Open-source and public-data notices

## DIVE QUANT PRO methodology

The consensus approach in `quant_engine.py` is a lightweight independent implementation inspired by the public methodology described by **Dive Into Crypto**:

- Project: https://github.com/nazmiefearmutcu/dive-into-crypto
- License: MIT
- Concepts used: weighted indicator consensus, regime-aware weighting, futures open-interest/funding/taker/top-trader context, explicit unavailable-data handling, and confidence/risk scoring.

This integration does **not** copy or vendor the upstream 60-indicator Python/Android source package. It currently implements 21 weighted indicator votes in a compact Python module, plus a Binance Futures microstructure overlay. The upstream project should be credited for the methodology; consult its repository for its complete license and implementation.

## Public market-data endpoints

- Binance Spot / USD-M Futures / Alpha public endpoints: no account API key is used.
- Yahoo Finance public chart and screener endpoints: no API key is used by this application. These endpoints are unofficial and may be delayed, rate-limited, geo-restricted, changed, or withdrawn. Their availability is not guaranteed.
- Missing market data is treated as unavailable; the engine must not generate synthetic candles or positioning values.

All signals are analytical estimates, not guaranteed returns or financial advice.
