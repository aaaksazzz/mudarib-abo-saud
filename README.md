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

## Open-source-inspired multi-strategy ensemble
- Market pages provide six independent analysis timeframes: **15m, 1h, 4h, 1d, 1w and 1M**. Each timeframe has its own closed-candle analysis, signal batch, entry, stop and targets.
- The ensemble combines independent EMA-trend, MACD-trend and RSI-trend votes with an NFI-inspired volume-breakout confirmation. A signal requires at least two aligned votes; this is a ranking/filtering design, not a verified win-rate model.
- Stop distance is **1 ATR (1R)** with staged targets at **1R, 2R and 3R**. Displayed confluence scores are not probabilities of profit.
- Spot, Alpha, US stocks and Tadawul remain long-only. Futures, US contracts and FX/metals can produce long and short signals.
- Binance Spot, USD-M Futures and Alpha use native candle intervals. Yahoo 4h candles are aggregated from hourly data; Yahoo chart history and interval availability vary by asset and may be delayed or rate-limited.
- Each timeframe is scanned on its own candle-close cadence: 15m, hourly, 4-hourly, daily, weekly and monthly. The scanner rotates a bounded candidate batch to limit provider load; coverage diagnostics report the universe and batch scanned.
- The engine uses completed candles only, checks signal freshness against each timeframe and preserves the market-wide direction filter. It does not claim to reproduce the complete NostalgiaForInfinity strategy or embed the Freqtrade bot framework.
- See [OPEN_SOURCE_NOTICES.md](OPEN_SOURCE_NOTICES.md) for source attribution, licenses and implementation boundaries. No upstream backtest result is represented as a SMART TRADING PRO performance result. Validate with out-of-sample tests, fees, spread and slippage before relying on signals.
## Signal engine
- Each successful timeframe scan replaces that timeframe's live batch, keeping up to three opportunities per market per timeframe. Previous rows remain in trade history and expire after 24 hours.
- Market-page requests only read committed results and never launch heavy scans synchronously.
- Expired records are also cleaned when the journal is read.
- No performance claim is made without reproducible per-market backtests.

## Production deployment
- Python runtime is pinned by `.python-version` to 3.12.
- Buildpack startup uses `Procfile`; Docker deployment is also supported.
- Expose port 8080.
- Configure a persistent PostgreSQL database through `DATABASE_URL`; SQLite is for CI/local checks only.
- Configure a persistent random `SECRET_KEY`, `COOKIE_SECURE=true`, and `ENABLE_AUTO_SCAN=true`.
- Keep one Gunicorn worker while APScheduler runs in-process. Do not increase workers until scanning is moved to a separate worker with a distributed lock.
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
