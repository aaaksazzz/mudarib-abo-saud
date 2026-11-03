# SMART TRADING PRO

A clean rebuild of the trading intelligence platform.

## Current foundation
- Responsive RTL-first dashboard shell.
- Independent navigation for each requested market.
- Dark/light theme toggle.
- Arabic/English language toggle.
- Explicit empty states: no fabricated prices, signals, win rates, or performance claims.
- Mobile navigation drawer.

## Planned implementation phases
1. **Foundation (current):** responsive shell, design system, navigation, theme and language.
2. **Identity and access:** secure registration/login, password reset, sessions, roles, subscription plans, individual grants and expiry.
3. **Administration:** section-level access switches, user management, subscription management, audit log and content moderation.
4. **Market data:** isolated adapters per market, source health, rate limits, caching and stale-data expiry.
5. **Strategy engine:** independently testable strategies, explainable scoring, risk sizing and market-specific validation.
6. **Trade lifecycle:** entry, TP1/TP2/TP3, stop, percentage calculations, status transitions and immutable outcome history.
7. **Editorial:** news ingestion with attribution, editorial review, categories, blog and publishing workflow.
8. **Quality and operations:** automated tests, security review, observability, deployment checks and backups.

## Backend setup
- Build and run with the included Dockerfile; the service listens on port 8080.
- Set `SECRET_KEY` to a persistent random secret.
- Set `DATABASE_URL` to a persistent PostgreSQL database. SQLite is for local smoke tests only; ephemeral container storage is not suitable for production accounts.
- Set `ADMIN_EMAIL` and a unique `ADMIN_PASSWORD` (at least 14 characters) before first boot to provision the first administrator.
- Binance public Spot and USDT-M perpetual Futures adapters are implemented. A 15-minute background scan checks a bounded list of the most liquid/fast-moving symbols and expires active records after 24 hours.
- Other markets are visible in the UI but are intentionally marked unconnected until real provider adapters and credentials are configured. Do not treat them as live.
- Manual subscription grants and section toggles are enforced by the server API. Payment checkout, email verification/password reset, and automated billing are not yet integrated.
- News and blog publishing are admin-managed; external news ingestion and source attribution workflow still need a provider/editorial setup.

## Important
The current repository foundation is a front-end shell only. Authentication, subscriptions, admin enforcement, live feeds and strategy execution are **not implemented yet**. They must be backed by server-side authorization and persistent storage; hiding a menu item in the browser is not access control.

Never store credentials in source control. Configure secrets only in the deployment environment and rotate any exposed credentials.
