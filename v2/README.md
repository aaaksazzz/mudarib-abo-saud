# SMART TRADING PRO V2 — isolated rebuild

This directory is a clean, non-production implementation. The existing application remains the production entrypoint until the V2 acceptance gates are met.

## Current first slice
- FastAPI API shell with provider-free liveness and market catalogue endpoints.
- API startup does not launch a scheduler or perform provider network calls.
- Explicit production configuration guards: no generated session secret and no silent SQLite fallback.
- React + TypeScript + Vite Arabic RTL market shell. It renders independently from market provider requests.
- Basic API tests.

## Run locally
API:
```bash
cd v2/backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload
```

Frontend:
```bash
cd v2/frontend
npm install
npm run dev
```

## Not production-ready yet
Authentication, persistent repositories, Alembic migrations, provider adapters, cached snapshots, scanner worker, trade lifecycle, browser tests, and deployment manifests are intentionally not wired yet. Do not point Northflank at this directory until the migration and shadow-run gates are complete.
