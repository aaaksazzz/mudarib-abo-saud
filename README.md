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

## Active engine: STP FALSE BREAKOUT CLOSE REVERSAL
- The single active entry logic is `breakout_50_strategy.py`, fingerprint `STP-FALSE-BREAKOUT-CLOSE-REVERSAL-V1-20261123`. Previous inverted Breakout 50 + Volume Profile logic and the separate US multi-setup entry logic are retired.
- All seven markets (Spot, Futures, Alpha, US stocks, US contracts, Saudi and Forex/Gold) use the same reversal rules on six completed-candle timeframes: 15m, 1h, 4h, 1d, 1w and 1M.
- BUY reversal: identify a confirmed prior swing low; require a later completed candle to break below that low and close below it; then wait for a subsequent completed candle to close above the high of that exact break candle. Only then is a BUY setup eligible.
- SELL reversal is the exact opposite: identify a confirmed prior swing high; require a later completed candle to break and close above it; then wait for a subsequent completed candle to close below the low of that exact break candle. Only then is a SELL setup eligible.
- The break candle's low/high defines structural invalidation, with an ATR-based safety buffer. Excessive stop distance is rejected using the timeframe's existing risk-distance ceiling.
- TP1/TP2/TP3 are 1R/2R/3R from the confirmed entry close. Signals use completed candles only and remain paper/manual; no account API keys or automatic order execution are used.
- The engine fingerprint and strategy diagnostics identify the new logic. Technical score is not a calibrated win probability and no strategy guarantees profits; validate with fees, spread, slippage and out-of-sample testing.

## Signal engine
- Each market and timeframe is evaluated independently. A signal requires a closed-candle breakout, 50% retracement, volume-profile confluence and a post-retest confirmation; the detected setup is then fully inverted before publishing the trade.
- A timeframe batch is replaced only when that scan produces at least one fresh setup. Previous rows remain in trade history and expire after 24 hours.
- Market-page requests only read committed results and never launch heavy scans synchronously. The staggered scanner continues on its configured schedule.
- Historical engine trades are superseded as the new engine scans each market; old strategy logic is not retained as a secondary signal source.
- The separate research backtester remains research-only and does not activate candidate strategies.

## Autonomous site manager
- The private administrator console is available at `/autopilot` after admin login.
- With `OPENAI_API_KEY` configured, the scheduler creates one original trading education article and one market-news digest per day from current Google News RSS headlines; publication is skipped when sources or model output fail validation.
- The AI reviewer checks one high-liquidity candidate per market twice daily across 15m, 1h, 4h, 1d, 1w and 1M. Any created trade is paper-only, uses structural validation and 1R/2R/3R targets, and expires after 24 hours.
- Hourly health checks record each market scanner state. A weekly design review may select one of three constrained, contrast-checked palettes; it cannot rewrite page source or deploy arbitrary code.
- AI jobs use a dedicated single-worker executor so remote model calls do not block the existing market scanner. Daily limits default to 14 AI market reviews and 120,000 total tokens; tune with `AI_AUTOPILOT_MAX_ANALYSES_PER_DAY` and `AI_AUTOPILOT_DAILY_TOKEN_LIMIT`.
- The site agent does not change user permissions, payments, credentials, subscription state, broker orders, or source code. Source-code/page-structure changes remain controlled GitHub deployments.

## AI company · 100 employees\n- The private owner console is available at `/company` after administrator login, with exactly 100 specialist agent seats across ten departments and an executive-agent role.\n- The owner can assign a scoped task to an employee. With `OPENAI_API_KEY` configured, the employee agent produces a deliverable and a separate CEO review is recorded. Meetings call each selected specialist agent independently, then pass the separate statements to the CEO agent for synthesis, decisions and follow-up actions. They are AI-agent meetings, not human meetings or evidence of all 100 agents running continuously.\n- Daily limits default to 20 task executions and 80,000 model tokens across the last 24 hours. Configure `AI_COMPANY_MAX_TASKS_PER_DAY` and `AI_COMPANY_DAILY_TOKEN_LIMIT` to change these limits.\n- Add `OPENAI_API_KEY` as a Northflank secret and restart the service to enable task execution and meeting generation. Without it, the employee directory and task queue remain available but AI work cannot run.\n- Employees have no access to broker credentials, customer passwords, payments, live order execution, or direct production deployment. Code changes require the normal reviewed GitHub deployment process.\n\n## Production deployment
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
