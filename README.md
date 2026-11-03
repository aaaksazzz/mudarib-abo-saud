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

## Important
The current repository foundation is a front-end shell only. Authentication, subscriptions, admin enforcement, live feeds and strategy execution are **not implemented yet**. They must be backed by server-side authorization and persistent storage; hiding a menu item in the browser is not access control.

Never store credentials in source control. Configure secrets only in the deployment environment and rotate any exposed credentials.
