# SMART TRADING PRO

Production-oriented market intelligence terminal.

## Implemented foundation
- Responsive Arabic RTL / English LTR interface with dark and light themes.
- Independent market sections with separate public data adapters. Missing provider data is treated as unavailable; the app does not fabricate prices or signals.
- Server-side authentication, role checks, section controls, subscription grants and audit history.
- Public read-only market signal pages and trade journal; administrative actions remain protected.
- Liveness endpoint `GET /health` and readiness endpoint `GET /ready`.

## Market data integrations
- **Binance Spot / USD-M Futures:** active USDT pairs and perpetual contracts, stablecoin base assets excluded, configured 24-hour quote-volume floor applied.
- **Binance Alpha:** public Alpha symbol, ticker and candle endpoints.
- **US stocks:** Yahoo public screeners are merged and filtered using 24-hour traded value of at least $1M. This is a broad public screener universe, not a guaranteed exhaustive list of every US-listed security.
- **US contracts:** the supported Yahoo futures-symbol list is filtered at $1M estimated 24-hour USD notional using each contract's multiplier; it is not a complete exchange directory.
- **Tadawul:** public Saudi Exchange data is preferred, with Yahoo, a public ticker directory and TradingView fallbacks. Saudi equities are not filtered by the $1M threshold; public-feed coverage can be incomplete during provider restrictions.
- **Forex & Gold:** public Yahoo symbol list; FX tick volume is not represented as exchange-traded dollar volume.

## Active engine: AS DAY-TRADER MULTI-SETUP ENGINE
- The previous inverted Breakout 50 + Volume Profile engine is retired. The single active engine is `breakout_50_strategy.py`, fingerprint `AS-DAYTRADER-MULTI-MARKET-V1-20261121`.
- Adapted multi-setup scanner evaluates completed candles across seven independent markets and six timeframes: 15m, 1h, 4h, 1d, 1w and 1M.
- Setups include 20-bar breakout/breakdown, bull/bear flag continuation, EMA20 reclaim/loss, and RSI oversold bounce/overbought rejection. Signals follow the detected direction; no full inversion.
- Spot is BUY-only. Other supported markets can produce BUY or SELL.
- Entry is based on the latest completed confirmation candle. Structural swing invalidation plus ATR buffer defines the stop; TP1/TP2/TP3 are 1R/2R/3R.
- Volume Profile and VWAP use candle OHLCV approximation. Binance aggregate-trade taker delta may support prioritized crypto symbols; other markets use a labelled candle-delta proxy.
- The score is a technical confluence score, not a calibrated win probability. No strategy guarantees profits. Backtesting and forward paper results after fees, spread, slippage and contract costs are required before relying on signals.
- The original upstream day-trader scanner/entry modules are US-stock/NYSE-session oriented; their market-specific code is not copied blindly into crypto, FX, Saudi or futures markets. The signal patterns and staged workflow are adapted to the app's existing public market adapters.
- Signals remain paper/manual only. No account API keys or automatic order execution are used.

## Production deployment
- Python runtime is pinned by `.python-version` to 3.15.2.
- Buildpack startup uses `Procfile`; Docker deployment is also supported.
- Expose port 8080.
- Prefer a persistent PostgreSQL database through `DATABASE_URL`. SQLite is acceptable only when `DATA_DIR` points to a persistent mounted volume; the default local SQLite path is not production-durable.
- Configure a persistent random `SECRET_KEY` and `COOKIE_SECURE=true`. The public sentiment dashboard scans on demand and does not require the legacy market scheduler.
- The active Breakout 50 + Volume Profile scanner runs on a staggered 15-minute schedule across markets. It uses public candle data and paper/manual signals only.
- `/ready` requires a durable database configuration (PostgreSQL or an explicitly configured `DATA_DIR` volume) and a persistent `SECRET_KEY`; no background market scheduler is required.
- Configure `ADMIN_EMAIL` and a unique `ADMIN_PASSWORD` (14+ characters) before first boot if first-admin provisioning is needed.
- Never commit or share secrets. Rotate credentials after any security incident and update them at the provider and deployment environment.

## Validation
GitHub Actions runs JavaScript syntax validation, dependency installation, Python compilation, backend regression tests, and route/static-asset smoke checks.

## Membership and manual payments
- Public pricing: USD 30 monthly, USD 171 for six months (5% off), USD 324 yearly (10% off).
- The public plans page shows the configured USDT TRC20, Solana and Binance account payment details.
- Payments are currently manual: a transfer does not automatically activate a subscription. An administrator verifies the transfer and grants access from the admin panel.
- Lifetime access is represented explicitly by `subscription_plan=lifetime` with no expiry date.
- Configure the administrator's email and a new unique password through Northflank secrets (`ADMIN_EMAIL`, `ADMIN_PASSWORD`); optionally set `ADMIN_USERNAME` for username login. Do not reuse a password posted in chat.
- The admin panel can save the official HTTPS contact link; the verified-style contact icon appears only after a destination is configured.
