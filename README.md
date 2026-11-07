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
- **US stocks / US contracts / Tadawul / Forex & Gold:** Yahoo Finance public screener and candle adapters for 15m, 1h, 4h (aggregated from hourly candles), 1d, 1w and 1M; US stocks apply the configured $1M traded-value floor and Tadawul does not.

## SMART FLOW QUANT engine
- Replaces the prior EMA/MACD/RSI/NFI-inspired strategy votes with price-structure, momentum, candle-pressure, relative-volume and range-expansion analysis.
- Optional Binance public aggTrades and order-book imbalance context is sampled for a limited number of leading Spot/Futures candidates; other markets use only their available provider data.
- The six independent analysis timeframes remain available: **15m, 1h, 4h, 1d, 1w and 1M**.
- Stops use recent swing structure with a volatility buffer; targets are 1R, 2R and 3R. Scores are confluence rankings, not probabilities.
- No private exchange API keys or automatic order execution are required. Market coverage and data quality depend on each provider.
- See [OPEN_SOURCE_NOTICES.md](OPEN_SOURCE_NOTICES.md) for data and methodology boundaries. Validate out of sample with fees, spread and slippage.

## Signal engine
- Each successful timeframe scan replaces that timeframe's live batch, keeping up to three opportunities per market per timeframe. Previous rows remain in trade history and expire after 24 hours.
- Market-page requests only read committed results and never launch heavy scans synchronously.
- Expired records are also cleaned when the journal is read.
- No performance claim is made without reproducible per-market backtests.

## Production deployment
- Python runtime is pinned by `.python-version` to 3.12.
- Buildpack startup uses `Procfile`; Docker deployment is also supported.
- Expose port 8080.
- Prefer a persistent PostgreSQL database through `DATABASE_URL`. SQLite is acceptable only when `DATA_DIR` points to a persistent mounted volume; the default local SQLite path is not production-durable.
- Configure a persistent random `SECRET_KEY`, `COOKIE_SECURE=true`, and `ENABLE_AUTO_SCAN=true`.
- Keep one Gunicorn worker while APScheduler runs in-process. Scans are scheduled independently per market with bounded cross-market concurrency; do not increase web workers until scanning is moved to a separate worker with a distributed lock.
- `/ready` requires a durable database configuration (PostgreSQL or an explicitly configured `DATA_DIR` volume), a persistent `SECRET_KEY`, and the market scheduler.
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
