from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from .settings import settings

@contextmanager
def connection():
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL غير مضبوط")
    # Short connection timeout + server-side statement timeout prevent a dead
    # PostgreSQL connection from freezing the web/worker indefinitely.
    with psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000",
        application_name="mudarib-abo-saud",
    ) as conn:
        yield conn

def init_db():
    # Advisory lock makes startup migrations safe when web and worker boot at
    # the same time against the same PostgreSQL database.
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7242026)")
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

        # Forward-compatible migrations for databases created by older builds.
        # CREATE TABLE IF NOT EXISTS does not modify an existing table, which
        # was the main source of "column/table missing" failures after deploys.
        migrations = [
            ("payments", "user_id", "BIGINT REFERENCES users(id) ON DELETE SET NULL"),
            ("payments", "plan", "TEXT NOT NULL DEFAULT '30d'"),
            ("payments", "txid", "TEXT NOT NULL DEFAULT ''"),
            ("payments", "status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("payments", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("signals", "market", "TEXT NOT NULL DEFAULT 'crypto'"),
            ("signals", "interval", "TEXT NOT NULL DEFAULT '15m'"),
            ("signals", "symbol", "TEXT NOT NULL DEFAULT ''"),
            ("signals", "direction", "TEXT NOT NULL DEFAULT 'حيادي'"),
            ("signals", "signal", "TEXT NOT NULL DEFAULT ''"),
            ("signals", "entry", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "tp1", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "tp2", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "tp3", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "sl", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "confidence", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "rr", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "trade_ready", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("signals", "status", "TEXT NOT NULL DEFAULT 'open'"),
            ("signals", "result", "TEXT NOT NULL DEFAULT ''"),
            ("signals", "pnl_percent", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("signals", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("signals", "resolved_at", "TIMESTAMPTZ"),
            ("signals", "candle_expires_at", "TIMESTAMPTZ"),
            ("market_cache", "payload", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
            ("market_cache", "updated_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("news", "slug", "TEXT"),
            ("news", "title", "TEXT NOT NULL DEFAULT ''"),
            ("news", "content", "TEXT NOT NULL DEFAULT ''"),
            ("news", "description", "TEXT NOT NULL DEFAULT ''"),
            ("news", "source", "TEXT NOT NULL DEFAULT 'المضارب ذكي'"),
            ("news", "category", "TEXT NOT NULL DEFAULT 'أخبار الأسواق'"),
            ("news", "link", "TEXT NOT NULL DEFAULT ''"),
            ("news", "published_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("blog_posts", "slug", "TEXT"),
            ("blog_posts", "title", "TEXT NOT NULL DEFAULT ''"),
            ("blog_posts", "excerpt", "TEXT NOT NULL DEFAULT ''"),
            ("blog_posts", "content", "TEXT NOT NULL DEFAULT ''"),
            ("blog_posts", "category", "TEXT NOT NULL DEFAULT 'عام'"),
            ("blog_posts", "cover_url", "TEXT NOT NULL DEFAULT ''"),
            ("blog_posts", "author", "TEXT NOT NULL DEFAULT 'المضارب ذكي'"),
            ("blog_posts", "published", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("blog_posts", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("blog_posts", "updated_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
        ]
        for table, column, definition in migrations:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")

        # Helpful indexes keep dashboard/admin/trade queries fast as history grows.
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_until)",
            "CREATE INDEX IF NOT EXISTS idx_payments_status_created ON payments(status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_signals_lookup ON signals(market, interval, symbol, status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_signals_open_review ON signals(status, candle_expires_at, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_signals_closed_stats ON signals(status, resolved_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_signals_symbol_created ON signals(symbol, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_blog_published ON blog_posts(published, created_at DESC)",
        ]
        for sql in indexes:
            conn.execute(sql)
