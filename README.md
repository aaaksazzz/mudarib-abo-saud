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

## Active strategy: SMART FLOW QUANT PRO · liquidity + volume + structural 3R
- The canonical engine fingerprint is `SMART-FLOW-LIQUIDITY-3R-MTF-V2-20261109`.
- All seven markets expose six independently scanned frames: 15m, 1h, 4h, 1d, 1w and 1M. Every frame is analyzed independently using its own completed candles; missing provider history is marked unavailable, never substituted with another frame.
- At least 200 valid completed candles from the requested frame are required. BUY/SELL direction uses the same-frame trend gate and market short-selling capability.
- Ranking combines price momentum, structure, relative volume, candle pressure, confirmed liquidity sweep/reclaim where present, OHLCV wick-rejection proxy, and optional Binance public trade-flow/order-book context. The score is a confluence score out of 100, not a win probability. OHLCV wick rejection is only an absorption proxy; true absorption requires trade-level order-flow data.
- Stops sit beyond recent structural invalidation with a volatility buffer; setups requiring a stop wider than 1.25% of entry are rejected. TP1, TP2 and TP3 are calculated from the actual entry-to-stop distance at 1R, 2R and 3R respectively, rather than fixed percentage targets.
- Fees, spread, slippage, funding, leverage and execution gaps can reduce realized R multiples. The 3R level is a gross price objective, not a guaranteed realized return. The platform is manual-only and never sends orders; validate out of sample with realistic costs before relying on any strategy.
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
- Keep one Gunicorn worker while APScheduler runs in-process. The seven market scans are staggered across each 15-minute cycle and dispatched by one scheduler worker to avoid simultaneous provider bursts and missed-job backlogs. Do not increase web workers until scanning is moved to a separate worker with a distributed lock.
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
