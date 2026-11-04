# Open-source and public-data notices

## DIVE Into Crypto indicator engine

The complete upstream `engine/` package from **Dive Into Crypto** is vendored under `dive_engine/engine/` and used by DIVE QUANT PRO.

- Upstream: https://github.com/nazmiefearmutcu/dive-into-crypto
- License: MIT; the upstream license is included as `DIVE_INTO_CRYPTO_LICENSE`.
- The vendored engine includes the upstream 60-indicator signal service, weighted consensus scorer, confidence/risk assessment and regime-adaptive weighting.
- This platform intentionally runs the engine on closed 15-minute candles only. The upstream Android/desktop scanner's 12-timeframe universe workflow is not enabled here.
- Binance Futures microstructure (open interest, top-trader/global long-short, taker buy/sell and funding) is an additive filter/annotation in `quant_engine.py`. Missing optional inputs remain unavailable and are never fabricated.
- Entry/stop/targets are platform-specific: one structural stop and TP1/TP2/TP3 at 1R/2R/3R.

## Public market-data endpoints

- Binance Spot / USD-M Futures / Alpha public endpoints: no account API key is used.
- Yahoo Finance public chart and screener endpoints: no API key is used by this application. These endpoints are unofficial and may be delayed, rate-limited, geo-restricted, changed, or withdrawn.
- The Saudi and US equity symbol lists are currently discovered through Yahoo's public screener. The screener response is bounded, so it does not prove every TASI or US listing is present.
- The scanner analyzes the 30 highest-24h-traded-value candidates per market in each scheduled cycle; Binance Futures positioning calls are limited to the top 12 candidates to control upstream rate limits.

All confidence values are model scores, not probabilities of profit. Signals are analytical estimates, not guaranteed returns or financial advice.
