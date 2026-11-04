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

## Market-specific 15m strategy candidate
- Market scans route through `market_strategies.py`: separate volume-expansion thresholds for Spot, Alpha, USD-M Futures, US stocks, US contracts, Tadawul and FX/metals.
- The setup requires a closed 15m impulse candle, elevated volume versus the prior 20 candles, and a decisive close in the directional half of the candle. Risk levels follow DIVE's ATR geometry using the 15m ATR(14): stop distance = 1.5×ATR; TP1 = 1×ATR, TP2 = 2×ATR, TP3 = 3×ATR from entry. These are distances, not 1R/2R/3R multiples of the stop; TP3 is 2R.
- Cash markets are long-only; derivatives and FX/metals can generate both directions. The module is intentionally dependency-light and uses the existing provider candle format.
- This is a research candidate, not a verified profitable strategy. Do not advertise a win rate or treat it as validated until walk-forward/out-of-sample tests include fees, spread, slippage and market-specific trading hours.
- **Binance USDT-M Futures:** active USDT perpetual contracts, excludes stablecoin base assets and applies the configured 24-hour quote-volume floor.
- Other market pages (Binance Alpha, US stocks, US contracts, Tadawul, Forex and Gold) remain unavailable until their provider adapter, universe, market-hours behavior and data quality are implemented and verified. Setting an API key alone does not make a market live.

## Signal engine
- Direction filter: 4-hour and daily candle trend must agree.
- Entry confirmation: closed 15-minute candles only; the still-forming candle is excluded.
- Ranking: absolute 15-minute change first, strength score and quote volume as tie-breakers.
- Risk: DIVE-style ATR geometry on 15m ATR(14): 1.5×ATR stop and 1×/2×/3×ATR targets.
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
