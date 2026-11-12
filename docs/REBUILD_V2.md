# SMART TRADING PRO — V2 Rebuild Plan

## Decision

Rebuild the application on a clean branch. Do not stack another feature patch on the existing monolith and do not merge the open historical pull requests as a batch. Preserve the current production branch until the replacement passes the acceptance gates below.

## Verified baseline findings (main branch)

- The backend is concentrated in `app.py` (about 76 KB): authentication, SQLAlchemy models, admin operations, provider HTTP calls, market snapshots, signal generation, trade lifecycle, scheduler, and routes share one module.
- The browser application is concentrated in `platform.js` (about 36 KB), with large HTML-string renderers and multiple page refresh paths.
- The home page currently awaits `/api/markets` and all seven market snapshot requests together. Each stale snapshot can synchronously call a third-party provider with retries and network timeouts. A slow provider can therefore delay the page.
- `/api/markets/<market>/snapshot` can perform provider I/O inside the request path instead of returning a cached snapshot immediately.
- The scanner is launched from the web application's import/startup path using APScheduler. This couples market scanning to web worker lifecycle and can create duplicate schedulers if web replicas/workers are increased.
- Each scan can create a thread pool of eight workers and analyze a rotating batch of up to 80 assets. This is aggressive for the currently documented 0.2 vCPU / 512 MB service.
- `Procfile` and `Dockerfile` specify different Gunicorn thread counts (4 versus 8), so deployment behavior can vary with the selected build path.
- A missing `SECRET_KEY` falls back to a newly generated random value at process startup, invalidating sessions after restarts.
- A missing `DATABASE_URL` and `DATA_DIR` falls back to a local SQLite file, which is not a safe durable production database on ephemeral container storage.
- Rate limiting uses in-memory storage by default; limits are not shared across replicas and reset on process restart.
- Schema creation and ad-hoc `ALTER TABLE` migrations run during application import/startup rather than through a versioned migration process.
- Current CI checks JavaScript syntax, Python compilation, strategy unit tests, and a route smoke test. It does not yet provide comprehensive API, database migration, provider-failure, scanner concurrency, browser, or load coverage.
- The repository currently has many open historical pull requests (including overlapping homepage, scanner, and strategy changes). They must be reviewed individually; they are not a safe release queue.

## Target architecture

### 1. API service
- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic migrations.
- Modular structure: `api/routes`, `domain`, `services`, `repositories`, `providers`, `schemas`, and `core`.
- Async HTTP clients with explicit connect/read/total timeouts, bounded concurrency, provider failover, retry budgets, and circuit-breaker behavior.
- Strict request/response schemas; consistent error envelope; request IDs; structured logs.
- Keep all trade actions manual-only. No broker order execution.

### 2. Market-data and scan worker
- A separately deployed worker, never started as a side effect of importing the web API.
- One scheduler owner and distributed/advisory locking to prevent duplicate scans.
- Cached market universes and snapshots; web requests read cached data and never wait for a full-market scan.
- Per-provider rate limits, bounded queues, back-pressure, and fair rotating cursors.
- Scan batches and concurrency selected from measured CPU/memory/provider limits, not guessed thread counts.
- Keep the current 15-minute closed-candle strategy requirement unless the product specification is deliberately changed.
- Preserve the requested 200-rule technical overlay as analysis/ranking and level calculation only; it must not become 200 mandatory gates or claim a proven win rate.

### 3. Frontend
- Vite + TypeScript with modular pages/components and a small static build served by the API/CDN.
- Arabic RTL as the default, English LTR, mobile-first dark professional UI.
- Typed API client, request cancellation, deduplicated requests, stale-while-revalidate data, and per-market error boundaries.
- Render the shell and cached homepage immediately; hydrate market cards independently.
- Remove duplicate timers, legacy timeframe requests, cascading compatibility styles, and unsafe ad-hoc HTML rendering.

### 4. Data and operations
- Durable PostgreSQL in production; no silent ephemeral SQLite fallback.
- Redis only if measured cache/queue/rate-limit needs justify its extra service and memory cost.
- Alembic versioned migrations with rollback/recovery plan.
- Secrets are mandatory and validated at startup; never generate a new production session secret automatically.
- One authoritative container command and one pinned dependency lock.
- Health and readiness checks distinguish process liveness, database readiness, provider status, and worker heartbeat.
- OpenTelemetry-compatible traces/metrics/logs; redact credentials and user data.

## Quality gates before any production switch

1. Unit tests for indicators, signal decisions, stops/targets, candle parsing, and market eligibility.
2. API integration tests for auth, CSRF, permissions, subscriptions, admin actions, and trade history.
3. Database migration tests against an empty database and a copy of the current schema/data.
4. Provider contract tests with recorded fixtures for timeouts, 429s, 403s, malformed data, empty universes, and partial outages.
5. Scanner tests for duplicate prevention, cursor fairness, closed-candle enforcement, bounded concurrency, and graceful shutdown.
6. Browser tests for every route, mobile layout, RTL/LTR, login flows, and slow/offline providers.
7. Load and soak tests with realistic seven-market traffic, checking p95/p99 latency, CPU, memory, database pool saturation, and provider rate limits.
8. Shadow deployment: compare V1 and V2 outputs without publishing or executing trades.
9. Production cutover only after all acceptance gates pass; retain a tested rollback to V1.

## Resource constraint

The current 0.2 vCPU / 512 MB instance is too small to assume that a web API and a multi-market scanner can both run comfortably. The rebuild must measure actual usage. If the service remains at this size, the scan worker must be tightly throttled or placed on a separately sized service. Do not compensate by spawning more threads or containers blindly.

## Release policy

- This branch is the isolated V2 rebuild workspace.
- Do not merge old open PRs wholesale.
- Do not deploy partial scaffolding.
- Do not replace the production service until migration, regression, browser, and load gates pass.


## Technology baseline — checked 2026-11-08

Use current stable releases, not alpha/beta/RC builds, for production:

- Python: target 3.15.2 after the full dependency and native-wheel compatibility matrix passes; retain Python 3.14.10 as the production fallback if any critical dependency is not yet certified on 3.15.
- FastAPI: 0.162.0.
- Starlette: 1.8.0 (FastAPI's compatible dependency resolver must select and lock the supported version).
- Node.js: 26 LTS (do not use Node 27 alpha for production builds).
- React: 19.3.
- TypeScript: 7.0 stable; do not use the 7.1 beta.
- Vite: 8.3 stable.
- PostgreSQL: 18.6 stable; do not deploy PostgreSQL 19 RC in production.
- Playwright: 1.65.0 for browser end-to-end testing.

Exact patch versions and transitive dependencies must be resolved in CI, committed to lockfiles, scanned for known vulnerabilities, and tested together. Never independently force a Starlette version that conflicts with FastAPI's declared constraints. Upgrade patch releases through automated CI and regression checks, not by floating production dependencies.
