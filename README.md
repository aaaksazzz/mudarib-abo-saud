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

## Active engine: STP BREAKOUT 50 + VOLUME PROFILE
- The single active signal engine is `breakout_50_strategy.py`, fingerprint `STP-BREAKOUT-50-VOLUME-PROFILE-V1-20261120`. The previous Price Action Quant / ICT-SMC / liquidity-sweep-FVG / full-inversion entry engines are retired and are not layered into this engine.
- Every market is scanned independently on six completed-candle timeframes: 15m, 1h, 4h, 1d, 1w and 1M. The engine has no day/night inversion and no higher-timeframe direction gate.
- BUY setup: confirmed close above a confirmed swing high, measure the breakout impulse, wait for a 50% retracement, require the retest to overlap the Volume Profile value area or be close to POC, then require a bullish post-retest structure confirmation.
- SELL setup is the exact inverse: confirmed close below a swing low, 50% upward retracement, Volume Profile confluence and bearish post-retest structure confirmation. Spot remains BUY-only because spot short selling is not supported by this terminal.
- Volume Profile provides POC, VAH and VAL. With OHLCV candles it is an explicitly labelled candle-volume approximation, not exchange-grade volume-at-price. VWAP is calculated from available candle volume.
- Binance Spot/Futures may add public aggregate-trade taker delta and order-book imbalance for a small prioritized subset. Other markets use a clearly labelled candle-delta proxy; it is not presented as true CVD or centralized FX volume.
- RSI momentum and ATR are supporting checks. ATR places the structural stop beyond the retest/impulse invalidation area. TP1/TP2/TP3 are 1R/2R/3R.
- The displayed score is a technical confluence score, not a statistically calibrated win probability. No strategy guarantees profits; no performance claim is made without reproducible per-market out-of-sample tests after fees, spread, slippage and contract-specific costs.
- Signals remain paper/manual only. No account API keys or automatic order execution are used.

## Signal engine
- Each market and timeframe is evaluated independently. A signal requires a closed-candle breakout, 50% retracement, volume-profile confluence and a post-retest confirmation; no single indicator can trigger an entry by itself.
- A timeframe batch is replaced only when that scan produces at least one fresh setup. Previous rows remain in trade history and expire after 24 hours.
- Market-page requests only read committed results and never launch heavy scans synchronously. The staggered scanner continues on its configured schedule.
- Historical engine trades are superseded as the new engine scans each market; old strategy logic is not retained as a secondary signal source.
- The separate research backtester remains research-only and does not activate candidate strategies.

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
