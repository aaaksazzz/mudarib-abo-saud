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

## Active engine: SWING-50 · independent multi-timeframe analysis
- Every market is analysed independently on 15m, 1h, 4h, 1d, 1w and 1M candles. No lower-timeframe direction gate is shared between frames.
- A setup requires a confirmed swing-high/swing-low pivot, a candle close beyond that level, a 50% retracement of the breakout impulse, and a closed-candle reversal confirmation at the retracement zone.
- BUY stop is placed beyond the original swing low; SELL stop is placed beyond the original swing high. A volatility buffer is added beyond the structural invalidation.
- TP1 is 1R, TP2 is 2R and TP3 is 3R from the live entry to the structural stop. The final target is 3:1 gross reward-to-risk before fees, spread, slippage or leverage.
- Only completed candles are used. Bullish BUY and mirrored bearish SELL setups are detected across all seven markets. On Spot, Alpha and equities, SELL is a manual exit/bearish signal, not a short-sale or automatic order.
- No account API keys or automatic order execution are used. A setup is not guaranteed to occur on every asset or timeframe; empty timeframe groups mean the rules were not fully met.
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
- Configure a persistent random `SECRET_KEY` and `COOKIE_SECURE=true`. The public sentiment dashboard scans on demand and does not require the legacy market scheduler.
- The retired SMA200/liquidity-sweep scheduler is disabled by default. Do not set `ENABLE_LEGACY_AUTO_SCAN=true` unless intentionally restoring the legacy scanner for diagnostics. The active SWING-50 engine scans each configured timeframe independently.
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
