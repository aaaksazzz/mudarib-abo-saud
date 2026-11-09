# SMART TRADING PRO — Clean Rebuild

This directory is the clean v2 foundation. It is intentionally introduced beside the live application so the production service, database, credentials, and existing deployment remain untouched until the replacement passes tests.

## Product rules
- Arabic-first RTL, dark professional theme, mobile-first compact cards.
- Preserve the existing SMART TRADING PRO visual direction; do not introduce a new unrelated visual identity.
- Homepage is market direction/overview only. Trading opportunities live inside their market pages.
- Manual trading only. Never submit orders or request exchange account credentials.
- Separate market adapters and isolated failures per market/provider.
- No fabricated prices, stale candles presented as live, or guaranteed win-rate claims.

## Strategy pipeline
1. Weekly candles determine the primary bias and label it: strong buy, buy, sell, or strong sell. Neutral/insufficient data means wait.
2. Daily candles are evaluated only after weekly bias exists. They must confirm or remain neutral; an opposing daily direction blocks entries.
3. Four-hour candles are evaluated next under the same rule. An opposing 4H direction blocks entries.
4. 15-minute completed candles are used only for the entry trigger, invalidation/stop, and TP1/TP2/TP3.
5. Cash markets (spot, Alpha, US stocks, Saudi) are long-only. Derivatives/FX may produce long or short setups.
6. Incomplete candles, missing timeframe data, stale data, or provider errors never produce a trade.

## Rebuild phases
- Phase A: isolate a clean strategy engine and deterministic tests.
- Phase B: build independent market-data/provider layer and bounded scan scheduler.
- Phase C: rebuild Flask/API application boundary and persistence migrations.
- Phase D: rebuild the RTL interface using the established product design language.
- Phase E: run unit, integration, market-adapter, mobile-layout, and live smoke tests.
- Phase F: deploy a parallel preview, verify it, then switch production. Do not delete the old app or database before verified cutover.

The current production application remains the fallback throughout the rebuild.