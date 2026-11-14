# Production deployment checklist

## Northflank
1. Keep the Buildpack runtime pinned by the root `.python-version` file (Python 3.15.2); the root `Procfile` defines the web process.
2. Expose HTTP port **8080**.
3. Configure a persistent PostgreSQL database and set `DATABASE_URL`. Do not rely on ephemeral SQLite for production accounts or trades.
4. Set a persistent random `SECRET_KEY`; changing it on every restart invalidates user sessions.
5. Set `COOKIE_SECURE=true` when serving over HTTPS.
6. Set `ENABLE_AUTO_SCAN=true` to run the in-process 15-minute scanner.
7. Keep exactly one Gunicorn worker while APScheduler is in the web process. More workers create duplicate schedulers and duplicate market scans. The seven market jobs are staggered across the 15-minute cycle and use one scheduler executor worker to avoid synchronized provider bursts.
8. Configure first-admin variables only through deployment secrets. Never paste credentials into GitHub, screenshots or chat.

## Current market adapters
- Binance Spot and Binance USDT-M perpetual Futures use public market endpoints; Binance account API keys are not required for these public feeds.
- The scan strategy evaluates closed 15m, 1h, 4h, 1d, 1w and 1M candles independently; each frame has its own scan bucket, cached results and trade-outcome replay.
- Market-page requests read cached database results and do not perform long-running scans.
- Binance Alpha, US equities, US contracts, Tadawul, Forex and Gold use public Yahoo/Binance adapters without account keys. Their symbol universes are provider-limited; the current Yahoo screeners do not guarantee a complete TASI or US-equity listing. Do not treat these lists as exhaustive.

## Health checks
- `GET /health`: process liveness only; HTTP 200 does not prove market scanning is ready.
- `GET /ready`: database connectivity, durable database configuration, a configured persistent secret and actual scheduler-running state. A 503 response means the service is not ready to serve production market data.
- GitHub Actions runs regression tests and smoke checks on each pull request.

## Operational safeguards
- Active trades expire after 24 hours.
- Scan failures are logged and do not advance the successful-scan timestamp.
- Do not advertise win rates or AI probabilities without a reproducible, fee-aware out-of-sample backtest.
- Rotate all user-defined credentials after a security incident, including deployment secrets and credentials at their issuing providers.
