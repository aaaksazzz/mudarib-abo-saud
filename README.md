# SMART TRADING PRO

Production-oriented market intelligence terminal.

## Implemented foundation
- Responsive Arabic RTL / English LTR interface with dark and light themes.
- Independent market sections; unintegrated markets are explicitly marked unavailable rather than filled with simulated prices or signals.
- Server-side authentication, role checks, section controls, subscription grants and audit history.
- Public read-only market signal pages and trade journal; administrative actions remain protected.
- Liveness endpoint `GET /health` and readiness endpoint `GET /ready`.

## Verified market integrations
- **Binance Spot:** USDT spot universe, active symbols only, excludes stablecoin base assets and applies the configured 24-hour quote-volume floor.
- **Binance USDT-M Futures:** active USDT perpetual contracts, excludes stablecoin base assets and applies the configured 24-hour quote-volume floor.
- Other market pages (Binance Alpha, US stocks, US contracts, Tadawul, Forex and Gold) remain unavailable until their provider adapter, universe, market-hours behavior and data quality are implemented and verified. Setting an API key alone does not make a market live.

## Signal engine
- Direction filter: 4-hour and daily candle trend must agree.
- Entry confirmation: closed 15-minute candles only; the still-forming candle is excluded.
- Ranking: absolute 15-minute change first, strength score and quote volume as tie-breakers.
- Risk: ATR-based stop and 1R / 2R / 3R targets.
- The scheduler runs Spot and Futures scans every 15 minutes. Market-page HTTP requests only read committed results and never launch a heavy scan synchronously.
- Active records expire after 24 hours. Expired records are also cleaned when the journal is read.
- A score is a ranking heuristic, not an AI probability or a verified win rate. No performance claim is made without a reproducible backtest.

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
