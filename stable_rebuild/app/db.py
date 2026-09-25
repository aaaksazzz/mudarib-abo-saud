from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from .settings import settings

@contextmanager
def connection():
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL غير مضبوط")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn

def init_db():
    with connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE, subscription_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS payments (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            plan TEXT NOT NULL, txid TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS signals (
            id BIGSERIAL PRIMARY KEY, market TEXT NOT NULL, interval TEXT NOT NULL,
            symbol TEXT NOT NULL, direction TEXT NOT NULL, signal TEXT NOT NULL DEFAULT '',
            entry DOUBLE PRECISION NOT NULL DEFAULT 0, tp1 DOUBLE PRECISION NOT NULL DEFAULT 0,
            tp2 DOUBLE PRECISION NOT NULL DEFAULT 0, tp3 DOUBLE PRECISION NOT NULL DEFAULT 0,
            sl DOUBLE PRECISION NOT NULL DEFAULT 0, confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            rr DOUBLE PRECISION NOT NULL DEFAULT 0, trade_ready BOOLEAN NOT NULL DEFAULT FALSE,
            status TEXT NOT NULL DEFAULT 'open', result TEXT NOT NULL DEFAULT '',
            pnl_percent DOUBLE PRECISION NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ, candle_expires_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_signals_lookup ON signals(market, interval, symbol, status, created_at DESC);
        CREATE TABLE IF NOT EXISTS market_cache (
            cache_key TEXT PRIMARY KEY, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS news (
            id BIGSERIAL PRIMARY KEY, slug TEXT UNIQUE, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'المضارب ذكي',
            category TEXT NOT NULL DEFAULT 'أخبار الأسواق', link TEXT NOT NULL DEFAULT '',
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS blog_posts (
            id BIGSERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            excerpt TEXT NOT NULL DEFAULT '', content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'عام',
            cover_url TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT 'المضارب ذكي',
            published BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
