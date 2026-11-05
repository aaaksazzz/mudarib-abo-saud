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
- **US stocks / US contracts / Tadawul / Forex & Gold:** Yahoo Finance public screener and 15m candle adapters; US stocks apply the configured $1M traded-value floor and Tadawul does not.

## Market-wide MiND-Shot-inspired VWAP strategy
- All seven market sections use the disclosed VWAP mean-reversion bracket logic from the public MiND-Shot project: rolling VWAP(20), price deviation z-score threshold of ±2, ADX(14) < 25, ATR(14) stop at 1.5×ATR, and the original TP1 at 0.75×ATR.
- The signal engine evaluates only completed **15-minute** candles. The market pages do not expose timeframe controls.
- TP2 (1.0×ATR) and TP3 (1.5×ATR) are staged extensions added for this platform's three-target card. They are not part of the source project's single-target bracket.
- Spot, Alpha, US stocks and Tadawul remain long-only. Futures, US contracts and FX/metals can produce long and short signals.
- The original repository's disclosed validation is BTC/ETH on 4h only. Applying its rules to other assets is a research adaptation, not proof those combinations are profitable. The source also warns that its results are in-sample and may weaken live.
- For feeds without exchange volume (notably some Yahoo FX candles), the engine explicitly falls back to an equal-weight typical-price proxy and labels the signal; it does not pretend the proxy is true volume-weighted VWAP. The scanner ranks the 20 most liquid eligible symbols per market and evaluates each on the 15-minute timeframe; this is a practical scan cap, not a claim that every listed symbol is evaluated on every cycle. It runs every 15 minutes.
- Signal scores are ranking heuristics, not AI win probabilities. Validate each market with out-of-sample tests, spread, fees and slippage before relying on signals.

## Signal engine
- Each successful market scan replaces the live opportunity batch, keeping up to three opportunities per market. Previous rows remain in trade history and expire after 24 hours.
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
