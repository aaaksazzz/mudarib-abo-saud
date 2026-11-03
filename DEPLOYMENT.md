# Production deployment checklist

## Northflank service
1. Build using the repository Dockerfile.
2. Expose HTTP port **8080**.
3. Set a persistent PostgreSQL database and mount/configure its connection as `DATABASE_URL`.
4. Set `SECRET_KEY` to a long random value and keep it stable between deploys.
5. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` before the first start. The first administrator is created only when no admin exists. Use a unique password of at least 14 characters.
6. Keep `COOKIE_SECURE=true` when serving over HTTPS.
7. Keep `ENABLE_AUTO_SCAN=true` for the 15-minute Spot/Futures scanner.
8. Never paste secrets into GitHub, source files, screenshots, or chat.

## Current integrations
- Binance Spot and Binance USDT-M perpetual Futures use public market endpoints; no Binance account key is needed for public market data.
- Alpha, US equities, US contracts, Tadawul, Forex and Gold are not live integrations in this milestone. Provider keys alone do not activate them; their adapters and symbol universes must be implemented and verified first.
- No payment processor, email delivery, verification or password-reset provider is configured. Subscription grants are manual through the admin console.
- The background scan runs in the single Gunicorn worker configured in Docker. Do not increase worker count unless the scanner is moved to a separate scheduled worker with a distributed lock.

## Smoke checks
- `GET /health` should return HTTP 200.
- `GET /api/bootstrap` should return the CSRF token and current account state.
- Register a test user, verify that signals/trade history are denied without an active subscription, then grant a short test subscription from the admin console.
- Verify that the admin can switch sections off and on.
- Confirm database persistence by restarting the service and checking that accounts and settings remain.
